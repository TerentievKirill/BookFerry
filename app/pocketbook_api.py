from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import secrets
from urllib.parse import quote

import requests
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, PlainTextResponse
from starlette.background import BackgroundTask

from app.db.catalogs import get_catalog, get_catalogs
from app.db.users import (
    get_user_by_uid,
    register_user,
    update_user_catalog,
    update_user_custom_opds,
)
from app.logging_config import log_event
from app.services.download import download_book, remove_book
from app.services.local_search import search_local_catalog
from app.services.opds import inspect_opds, search_opds


router = APIRouter(prefix="/pocketbook", tags=["PocketBook"])
logger = logging.getLogger("bookferry.pocketbook")

MAX_TOKEN_LENGTH = 4096
MAX_QUERY_LENGTH = 256
TOKEN_SIGNATURE_LENGTH = 16
_TOKEN_SECRET = (
    os.environ.get("POCKETBOOK_TOKEN_SECRET", "").encode("utf-8")
    or secrets.token_bytes(32)
)


def _plain(text: str) -> PlainTextResponse:
    return PlainTextResponse(
        text,
        headers={"Cache-Control": "no-store"},
    )


def _encode_text(value: str | None) -> str:
    return quote(value or "", safe="")


def _encode_token(value: str) -> str:
    payload = value.encode("utf-8")
    signature = hmac.new(
        _TOKEN_SECRET,
        payload,
        hashlib.sha256,
    ).digest()[:TOKEN_SIGNATURE_LENGTH]

    return base64.urlsafe_b64encode(
        signature + payload
    ).decode("ascii").rstrip("=")


def _decode_token(token: str) -> str:
    if not token or len(token) > MAX_TOKEN_LENGTH:
        raise HTTPException(
            status_code=400,
            detail="Некорректный token",
        )

    padding = "=" * (-len(token) % 4)

    try:
        raw = base64.urlsafe_b64decode(token + padding)
    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail="Некорректный token",
        ) from error

    if len(raw) <= TOKEN_SIGNATURE_LENGTH:
        raise HTTPException(
            status_code=400,
            detail="Некорректный token",
        )

    signature = raw[:TOKEN_SIGNATURE_LENGTH]
    payload = raw[TOKEN_SIGNATURE_LENGTH:]
    expected = hmac.new(
        _TOKEN_SECRET,
        payload,
        hashlib.sha256,
    ).digest()[:TOKEN_SIGNATURE_LENGTH]

    if not hmac.compare_digest(signature, expected):
        raise HTTPException(
            status_code=400,
            detail="Некорректный token",
        )

    try:
        value = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise HTTPException(
            status_code=400,
            detail="Некорректный token",
        ) from error

    if not value:
        raise HTTPException(
            status_code=400,
            detail="Пустой token",
        )

    return value


def _pocketbook_user(uid: str):
    user = get_user_by_uid(uid)
    if user is None or user["client_type"] != "pocketbook":
        raise HTTPException(
            status_code=404,
            detail="PocketBook не зарегистрирован",
        )
    return user


def _active_catalog(catalog_id: int):
    catalog = get_catalog(catalog_id)
    if catalog is None or not catalog["enabled"]:
        raise HTTPException(
            status_code=404,
            detail="Библиотека не найдена",
        )
    return catalog


def _catalog_by_base_url(opds_url: str):
    normalized = opds_url.strip().rstrip("/")
    return next(
        (
            item
            for item in get_catalogs()
            if item["base_url"].strip().rstrip("/") == normalized
        ),
        None,
    )


def _search_for_user(
    user,
    query: str,
    page_url: str | None,
):
    if user["custom_opds_url"]:
        books, next_page_url = search_opds(
            url=user["custom_opds_url"],
            query=query,
            page_url=page_url,
            search_template=user["custom_opds_search_template"],
        )
        return books, next_page_url, "custom_opds"

    catalog = _active_catalog(user["catalog_id"])
    books, next_page_url = search_local_catalog(
        catalog_code=catalog["code"],
        base_url=catalog["base_url"],
        query=query,
        page_token=page_url,
    )
    return books, next_page_url, catalog["code"]


@router.get("/register", response_class=PlainTextResponse)
def register_pocketbook(request: Request):
    try:
        user = register_user("pocketbook")
    except ValueError as error:
        raise HTTPException(
            status_code=500,
            detail=str(error),
        ) from error

    catalog = _active_catalog(user["catalog_id"])

    log_event(
        logger,
        request,
        "PB_REGISTERED",
        uid=user["uid"],
        catalog_id=catalog["id"],
        catalog_code=catalog["code"],
    )

    return _plain(
        "UID\t"
        f"{user['uid']}\t"
        f"{catalog['id']}\t"
        f"{_encode_text(catalog['name'])}\n"
    )


@router.get("/catalogs", response_class=PlainTextResponse)
def pocketbook_catalogs(request: Request):
    catalogs = [
        catalog
        for catalog in get_catalogs()
        if catalog["enabled"]
    ]

    lines = [
        f"CATALOG\t{catalog['id']}\t{_encode_text(catalog['name'])}"
        for catalog in catalogs
    ]
    lines.append(f"CUSTOM\t{_encode_text('Другой OPDS')}")

    log_event(
        logger,
        request,
        "PB_CATALOGS",
        count=len(catalogs),
    )

    return _plain("\n".join(lines) + "\n")


@router.get("/{uid}/profile", response_class=PlainTextResponse)
def pocketbook_profile(uid: str, request: Request):
    user = _pocketbook_user(uid)

    if user["custom_opds_url"]:
        mode = "custom"
        name = "Другой OPDS"
        source_url = user["custom_opds_url"]
    else:
        catalog = _active_catalog(user["catalog_id"])
        mode = "catalog"
        name = catalog["name"]
        source_url = catalog["base_url"]

    log_event(
        logger,
        request,
        "PB_PROFILE",
        uid=uid,
        mode=mode,
        catalog_id=user["catalog_id"],
    )

    return _plain(
        "PROFILE\t"
        f"{user['catalog_id']}\t"
        f"{_encode_text(name)}\t"
        f"{mode}\t"
        f"{_encode_text(source_url)}\n"
    )


@router.get("/{uid}/catalog/{catalog_id}", response_class=PlainTextResponse)
def pocketbook_set_catalog(
    uid: str,
    catalog_id: int,
    request: Request,
):
    _pocketbook_user(uid)
    catalog = _active_catalog(catalog_id)

    if not update_user_catalog(uid, catalog["id"]):
        raise HTTPException(
            status_code=500,
            detail="Не удалось сохранить библиотеку",
        )

    log_event(
        logger,
        request,
        "PB_CATALOG_CHANGED",
        uid=uid,
        catalog_id=catalog["id"],
        catalog_code=catalog["code"],
        catalog_name=catalog["name"],
    )

    return _plain(
        f"OK\t{catalog['id']}\t{_encode_text(catalog['name'])}\n"
    )


@router.get("/{uid}/opds", response_class=PlainTextResponse)
def pocketbook_set_opds(
    uid: str,
    request: Request,
    url: str = Query(min_length=8, max_length=1024),
):
    _pocketbook_user(uid)
    normalized_url = url.strip()

    builtin = _catalog_by_base_url(normalized_url)
    if builtin is not None:
        update_user_catalog(uid, builtin["id"])
        log_event(
            logger,
            request,
            "PB_CATALOG_CHANGED",
            uid=uid,
            catalog_id=builtin["id"],
            catalog_code=builtin["code"],
            catalog_name=builtin["name"],
        )
        return _plain(
            f"OK\t{builtin['id']}\t{_encode_text(builtin['name'])}\n"
        )

    try:
        final_url, search_template = inspect_opds(normalized_url)
    except requests.RequestException as error:
        log_event(
            logger,
            request,
            "PB_OPDS_ERROR",
            level=logging.WARNING,
            uid=uid,
            opds_url=normalized_url,
            error=str(error),
        )
        raise HTTPException(
            status_code=502,
            detail=f"Не удалось открыть OPDS: {error}",
        ) from error
    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error),
        ) from error

    if not update_user_custom_opds(
        uid=uid,
        opds_url=final_url,
        search_template=search_template,
    ):
        raise HTTPException(
            status_code=500,
            detail="Не удалось сохранить OPDS",
        )

    log_event(
        logger,
        request,
        "PB_OPDS_CHANGED",
        uid=uid,
        opds_url=final_url,
    )

    return _plain(
        f"OK\t0\t{_encode_text('Другой OPDS')}\n"
    )


@router.get("/{uid}/search", response_class=PlainTextResponse)
def pocketbook_search(
    uid: str,
    request: Request,
    q: str = Query(min_length=1, max_length=MAX_QUERY_LENGTH),
    page: str | None = Query(default=None, max_length=MAX_TOKEN_LENGTH),
):
    user = _pocketbook_user(uid)
    query = q.strip()

    if not query:
        raise HTTPException(
            status_code=400,
            detail="Пустой поисковый запрос",
        )

    page_url = _decode_token(page) if page else None

    log_event(
        logger,
        request,
        "PB_SEARCH",
        uid=uid,
        query=query,
        page="next" if page else "first",
    )

    try:
        books, next_page_url, source = _search_for_user(
            user=user,
            query=query,
            page_url=page_url,
        )
    except requests.RequestException as error:
        log_event(
            logger,
            request,
            "PB_SEARCH_ERROR",
            level=logging.WARNING,
            uid=uid,
            query=query,
            error=str(error),
        )
        raise HTTPException(
            status_code=502,
            detail=f"Библиотека недоступна: {error}",
        ) from error
    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error),
        ) from error

    lines = [f"COUNT\t{len(books)}"]
    for book in books:
        lines.append(
            "BOOK\t"
            f"{_encode_text(book.title)}\t"
            f"{_encode_text(book.author)}\t"
            f"{_encode_token(book.url)}"
        )

    if next_page_url:
        lines.append(f"NEXT\t{_encode_token(next_page_url)}")

    log_event(
        logger,
        request,
        "PB_SEARCH_RESULT",
        uid=uid,
        source=source,
        query=query,
        found=len(books),
        has_more=bool(next_page_url),
    )

    return _plain("\n".join(lines) + "\n")


@router.get("/{uid}/download/{token}")
def pocketbook_download(
    uid: str,
    token: str,
    request: Request,
):
    _pocketbook_user(uid)
    book_url = _decode_token(token)

    log_event(
        logger,
        request,
        "PB_DOWNLOAD",
        uid=uid,
        url=book_url,
    )

    try:
        path = download_book(book_url)
    except requests.RequestException as error:
        log_event(
            logger,
            request,
            "PB_DOWNLOAD_ERROR",
            level=logging.WARNING,
            uid=uid,
            url=book_url,
            error=str(error),
        )
        raise HTTPException(
            status_code=502,
            detail=f"Не удалось скачать книгу: {error}",
        ) from error
    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error),
        ) from error

    filename = os.path.basename(path)

    log_event(
        logger,
        request,
        "PB_DOWNLOAD_RESULT",
        uid=uid,
        filename=filename,
        result="success",
    )

    return FileResponse(
        path=path,
        filename=filename,
        media_type="application/epub+zip",
        background=BackgroundTask(remove_book, path),
    )
