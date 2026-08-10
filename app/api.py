import logging
import os
import sqlite3
import time
from urllib.parse import quote

import requests
from fastapi import APIRouter, Body, HTTPException, Query, Request
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from starlette.background import BackgroundTask

from app.db.catalogs import get_catalog, get_catalogs
from app.db.users import (
    create_user,
    get_user,
    get_user_by_uid,
    register_user,
    touch_user,
    update_email,
    update_subject,
    update_telegram_catalog,
    update_telegram_custom_opds,
    update_user_catalog,
    update_user_custom_opds,
    update_user_emails,
    update_user_subject,
)
from app.logging_config import log_event
from app.models import (
    CatalogUpdate,
    EmailsUpdate,
    OpdsUpdate,
    RegisterUserRequest,
    SearchRequest,
    SearchResponse,
    SendBookRequest,
    SubjectUpdate,
    TelegramUser,
    User,
)
from app.services.download import (
    download_book,
    iter_book_stream,
    open_book_stream,
    remove_book,
)
from app.services.local_search import search_local_catalog
from app.services.mail import send_file
from app.services.opds import inspect_opds, search_opds


router = APIRouter()
logger = logging.getLogger("bookferry.api")


def _books_sample(books, limit: int = 5) -> str:
    if not books:
        return "-"
    return " | ".join(
        f"{book.title} — {book.author or '-'}"
        for book in books[:limit]
    )


def _email_count(value: str | None) -> int:
    if not value:
        return 0
    return len([item for item in value.split(",") if item.strip()])


def _active_catalog(catalog_id: int):
    catalog = get_catalog(catalog_id)
    if catalog is None or not catalog["enabled"]:
        raise HTTPException(status_code=404, detail="Активный каталог не найден")
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


def _inspect_custom_opds(opds_url: str) -> tuple[str, str]:
    try:
        return inspect_opds(opds_url)
    except requests.RequestException as error:
        raise HTTPException(
            status_code=502,
            detail=f"Не удалось открыть OPDS: {error}",
        ) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


def _resolve_user(
    *,
    telegram_id: int | None = None,
    uid: str | None = None,
):
    if (telegram_id is None) == (uid is None):
        raise HTTPException(
            status_code=400,
            detail="Нужно передать telegram_id или uid",
        )

    user = get_user(telegram_id) if telegram_id is not None else get_user_by_uid(uid)
    if user is None:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    touch_user(user["uid"])
    return user


def _log_identity(user) -> dict:
    fields = {
        "uid": user["uid"],
        "client_type": user["client_type"],
    }
    if user["client_type"] == "telegram" and user["external_id"]:
        fields["telegram_id"] = user["external_id"]
    return fields


def _search_for_user(user, query: str, page_url: str | None):
    if user["custom_opds_url"]:
        books, next_page_url = search_opds(
            url=user["custom_opds_url"],
            query=query,
            page_url=page_url,
            search_template=user["custom_opds_search_template"],
        )
        return books, next_page_url, "custom_opds", user["custom_opds_url"]

    catalog = _active_catalog(user["catalog_id"])
    books, next_page_url = search_local_catalog(
        catalog_code=catalog["code"],
        base_url=catalog["base_url"],
        query=query,
        page_token=page_url,
    )
    return books, next_page_url, catalog["code"], catalog["base_url"]


def _search_result(
    request: Request,
    user,
    query: str,
    page_url: str | None,
    plain: bool,
):
    identity = _log_identity(user)
    log_event(
        logger,
        request,
        "SEARCH",
        **identity,
        query=query,
        page=page_url or "first",
    )

    source = "unknown"
    try:
        books, next_page_url, source, source_url = _search_for_user(
            user,
            query,
            page_url,
        )
    except requests.RequestException as error:
        log_event(
            logger,
            request,
            "SEARCH_ERROR",
            level=logging.WARNING,
            **identity,
            source=source,
            query=query,
            error=str(error),
        )
        raise HTTPException(
            status_code=502,
            detail=f"OPDS-каталог недоступен: {error}",
        ) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    log_event(
        logger,
        request,
        "SEARCH_RESULT",
        **identity,
        source=source,
        source_url=source_url,
        query=query,
        found=len(books),
        next_page=next_page_url,
        sample=_books_sample(books),
    )

    if plain:
        lines = [f"COUNT\t{len(books)}"]
        for book in books:
            lines.append(
                "BOOK\t"
                f"{quote(book.title or '', safe='')}\t"
                f"{quote(book.author or '', safe='')}\t"
                f"{quote(book.url, safe='')}"
            )
        if next_page_url:
            lines.append(f"NEXT\t{quote(next_page_url, safe='')}")
        return PlainTextResponse("\n".join(lines) + "\n")

    return SearchResponse(books=books, next_page_url=next_page_url)


def _stream_pocketbook_download(request: Request, identity: dict, url: str):
    started = time.perf_counter()

    try:
        upstream, filename = open_book_stream(url)
    except requests.RequestException as error:
        log_event(
            logger,
            request,
            "DOWNLOAD_ERROR",
            level=logging.WARNING,
            **identity,
            url=url,
            error=str(error),
        )
        raise HTTPException(
            status_code=502,
            detail=f"Не удалось скачать книгу: {error}",
        ) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    headers = {
        "Content-Disposition": (
            "attachment; filename*=UTF-8''"
            f"{quote(filename, safe='')}"
        ),
    }

    content_length = upstream.headers.get("Content-Length")
    if (
        content_length
        and content_length.isdigit()
        and not upstream.headers.get("Content-Encoding")
    ):
        headers["Content-Length"] = content_length

    open_ms = (time.perf_counter() - started) * 1000
    log_event(
        logger,
        request,
        "DOWNLOAD_STREAM_READY",
        **identity,
        filename=filename,
        content_length=content_length,
        upstream_open_ms=round(open_ms, 1),
    )

    def body():
        transferred = 0
        try:
            for chunk in iter_book_stream(upstream):
                transferred += len(chunk)
                yield chunk

            elapsed_ms = (time.perf_counter() - started) * 1000
            log_event(
                logger,
                request,
                "DOWNLOAD_RESULT",
                **identity,
                filename=filename,
                bytes=transferred,
                duration_ms=round(elapsed_ms, 1),
                result="success",
            )
        except Exception as error:
            elapsed_ms = (time.perf_counter() - started) * 1000
            log_event(
                logger,
                request,
                "DOWNLOAD_ERROR",
                level=logging.ERROR,
                **identity,
                filename=filename,
                bytes=transferred,
                duration_ms=round(elapsed_ms, 1),
                error=str(error),
            )
            raise

    return StreamingResponse(
        body(),
        media_type="application/epub+zip",
        headers=headers,
    )


def _download_result(request: Request, user, url: str):
    identity = _log_identity(user)
    log_event(logger, request, "DOWNLOAD", **identity, url=url)

    if user["client_type"] == "pocketbook":
        return _stream_pocketbook_download(request, identity, url)

    try:
        path = download_book(url)
    except requests.RequestException as error:
        log_event(
            logger,
            request,
            "DOWNLOAD_ERROR",
            level=logging.WARNING,
            **identity,
            url=url,
            error=str(error),
        )
        raise HTTPException(
            status_code=502,
            detail=f"Не удалось скачать книгу: {error}",
        ) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    emails = [
        email.strip()
        for email in (user["emails"] or "").split(",")
        if email.strip()
    ]

    try:
        for email in emails:
            send_file(recipient_email=email, file_path=path)

        log_event(
            logger,
            request,
            "DOWNLOAD_RESULT",
            **identity,
            filename=os.path.basename(path),
            email_count=len(emails),
            result="success",
        )

        return FileResponse(
            path=path,
            filename=os.path.basename(path),
            media_type="application/epub+zip",
            background=BackgroundTask(remove_book, path),
        )
    except Exception as error:
        remove_book(path)
        log_event(
            logger,
            request,
            "DOWNLOAD_ERROR",
            level=logging.ERROR,
            **identity,
            error=str(error),
        )
        raise


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/search")
def search_get(
    request: Request,
    query: str = Query(min_length=1, max_length=256),
    page_url: str | None = None,
    telegram_id: int | None = None,
    uid: str | None = None,
    plain: bool = False,
):
    user = _resolve_user(telegram_id=telegram_id, uid=uid)
    return _search_result(request, user, query.strip(), page_url, plain)


@router.post("/search", response_model=SearchResponse)
def search_post(data: SearchRequest, request: Request):
    """Compatibility for the current Telegram bot. New clients use GET /search."""
    user = _resolve_user(telegram_id=data.telegram_id)
    return _search_result(request, user, data.query.strip(), data.page_url, False)


@router.get("/download")
def download_get(
    request: Request,
    url: str,
    telegram_id: int | None = None,
    uid: str | None = None,
):
    user = _resolve_user(telegram_id=telegram_id, uid=uid)
    return _download_result(request, user, url)


@router.post("/send-book")
def send_book_post(data: SendBookRequest, request: Request):
    """Compatibility for the current Telegram bot. New clients use GET /download."""
    user = _resolve_user(telegram_id=data.telegram_id)
    return _download_result(request, user, data.url)


@router.get("/users/telegram/{telegram_id}", response_model=TelegramUser)
def get_telegram_user(telegram_id: int, request: Request):
    user = get_user(telegram_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Пользователь Telegram не найден")

    touch_user(user["uid"])
    log_event(logger, request, "PROFILE_READ", telegram_id=telegram_id, result="success")
    return TelegramUser(
        id=user["id"],
        uid=user["uid"],
        telegram_id=int(user["external_id"]),
        catalog_id=user["catalog_id"],
        opds_url=user["opds_url"],
        emails=user["emails"],
        subject=user["subject"],
    )


@router.patch("/users/telegram/{telegram_id}/opds")
def set_telegram_user_opds(
    telegram_id: int,
    request: Request,
    opds_url: str = Body(..., embed=True),
):
    if get_user(telegram_id) is None:
        create_user(telegram_id)

    builtin = _catalog_by_base_url(opds_url)
    if builtin is not None:
        update_telegram_catalog(telegram_id, builtin["id"])
        return {
            "status": "ok",
            "mode": "catalog",
            "catalog_id": builtin["id"],
            "opds_url": builtin["base_url"],
        }

    final_url, search_template = _inspect_custom_opds(opds_url.strip())
    if not update_telegram_custom_opds(
        telegram_id=telegram_id,
        opds_url=final_url,
        search_template=search_template,
    ):
        raise HTTPException(status_code=500, detail="Не удалось сохранить OPDS")

    return {"status": "ok", "mode": "custom", "opds_url": final_url}


@router.patch("/users/telegram/{telegram_id}/catalog")
def set_telegram_user_catalog(
    telegram_id: int,
    data: CatalogUpdate,
    request: Request,
):
    if get_user(telegram_id) is None:
        create_user(telegram_id)

    catalog = _active_catalog(data.catalog_id)
    update_telegram_catalog(telegram_id, catalog["id"])
    log_event(
        logger,
        request,
        "CATALOG_CHANGED",
        telegram_id=telegram_id,
        catalog_id=catalog["id"],
        catalog_code=catalog["code"],
    )
    return {
        "status": "ok",
        "catalog_id": catalog["id"],
        "opds_url": catalog["base_url"],
    }


@router.patch("/users/telegram/{telegram_id}/emails")
def set_telegram_user_emails(
    telegram_id: int,
    request: Request,
    emails: str = Body(..., embed=True),
):
    if get_user(telegram_id) is None:
        raise HTTPException(status_code=404, detail="Пользователь Telegram не найден")

    normalized = emails.strip()
    if not update_email(telegram_id=telegram_id, emails=normalized):
        raise HTTPException(status_code=500, detail="Не удалось сохранить email")

    log_event(
        logger,
        request,
        "EMAILS_CHANGED",
        telegram_id=telegram_id,
        email_count=_email_count(normalized),
    )
    return {"status": "ok", "emails": normalized}


@router.patch("/users/telegram/{telegram_id}/subject")
def set_telegram_user_subject(
    telegram_id: int,
    request: Request,
    subject: str | None = Body(default=None, embed=True),
):
    normalized = subject.strip() if subject else None
    if not update_subject(telegram_id=telegram_id, subject=normalized):
        raise HTTPException(status_code=404, detail="Пользователь Telegram не найден")

    log_event(
        logger,
        request,
        "SUBJECT_CHANGED",
        telegram_id=telegram_id,
        action="set" if normalized else "cleared",
    )
    return {"status": "ok", "subject": normalized}


@router.get("/catalogs")
def list_catalogs(plain: bool = False):
    catalogs = [dict(catalog) for catalog in get_catalogs() if catalog["enabled"]]
    if plain:
        lines = [
            f"CATALOG\t{catalog['id']}\t{quote(catalog['name'], safe='')}"
            for catalog in catalogs
        ]
        lines.append(f"CUSTOM\t{quote('Другой OPDS', safe='')}")
        return PlainTextResponse("\n".join(lines) + "\n")
    return catalogs


@router.post("/users/register", response_model=User, status_code=201)
def create_generic_user(data: RegisterUserRequest, request: Request):
    try:
        user = register_user(data.client_type, data.external_id)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except sqlite3.IntegrityError as error:
        raise HTTPException(status_code=409, detail="Пользователь уже существует") from error

    log_event(
        logger,
        request,
        "USER_REGISTERED",
        uid=user["uid"],
        client_type=data.client_type,
        external_id=data.external_id,
    )
    return User(**dict(user))


@router.get("/users/register")
def create_generic_user_get(
    request: Request,
    client_type: str,
    external_id: str | None = None,
    plain: bool = False,
):
    try:
        user = register_user(client_type, external_id)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    catalog = _active_catalog(user["catalog_id"])
    log_event(
        logger,
        request,
        "USER_REGISTERED",
        uid=user["uid"],
        client_type=client_type,
        external_id=external_id,
    )

    if plain:
        return PlainTextResponse(
            "UID\t"
            f"{user['uid']}\t"
            f"{catalog['id']}\t"
            f"{quote(catalog['name'], safe='')}\n"
        )
    return User(**dict(user))


@router.get("/users/{uid}", response_model=None)
def get_generic_user(uid: str, request: Request, plain: bool = False):
    user = get_user_by_uid(uid)
    if user is None:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    touch_user(uid)
    log_event(logger, request, "PROFILE_READ", uid=uid, result="success")

    if plain:
        if user["custom_opds_url"]:
            mode = "custom"
            name = "Другой OPDS"
            source_url = user["custom_opds_url"]
        else:
            catalog = _active_catalog(user["catalog_id"])
            mode = "catalog"
            name = catalog["name"]
            source_url = catalog["base_url"]

        return PlainTextResponse(
            "PROFILE\t"
            f"{user['catalog_id']}\t"
            f"{quote(name, safe='')}\t"
            f"{mode}\t"
            f"{quote(source_url, safe='')}\n"
        )

    return User(**dict(user))


@router.patch("/users/{uid}/catalog")
def set_user_catalog(uid: str, data: CatalogUpdate, request: Request):
    if get_user_by_uid(uid) is None:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    catalog = _active_catalog(data.catalog_id)
    update_user_catalog(uid, catalog["id"])
    log_event(logger, request, "CATALOG_CHANGED", uid=uid, catalog_id=catalog["id"])
    return {
        "status": "ok",
        "catalog_id": catalog["id"],
        "opds_url": catalog["base_url"],
    }


@router.get("/users/{uid}/catalog")
def set_user_catalog_get(
    uid: str,
    catalog_id: int,
    request: Request,
    plain: bool = False,
):
    if get_user_by_uid(uid) is None:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    catalog = _active_catalog(catalog_id)
    update_user_catalog(uid, catalog["id"])
    log_event(logger, request, "CATALOG_CHANGED", uid=uid, catalog_id=catalog["id"])

    if plain:
        return PlainTextResponse(
            f"OK\t{catalog['id']}\t{quote(catalog['name'], safe='')}\n"
        )
    return {
        "status": "ok",
        "catalog_id": catalog["id"],
        "opds_url": catalog["base_url"],
    }


@router.patch("/users/{uid}/opds")
def set_user_opds(uid: str, data: OpdsUpdate, request: Request):
    return _set_user_opds(uid, data.opds_url, request, False)


@router.get("/users/{uid}/opds")
def set_user_opds_get(
    uid: str,
    request: Request,
    opds_url: str,
    plain: bool = False,
):
    return _set_user_opds(uid, opds_url, request, plain)


def _set_user_opds(uid: str, opds_url: str, request: Request, plain: bool):
    if get_user_by_uid(uid) is None:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    builtin = _catalog_by_base_url(opds_url)
    if builtin is not None:
        update_user_catalog(uid, builtin["id"])
        if plain:
            return PlainTextResponse(
                f"OK\t{builtin['id']}\t{quote(builtin['name'], safe='')}\n"
            )
        return {
            "status": "ok",
            "mode": "catalog",
            "catalog_id": builtin["id"],
            "opds_url": builtin["base_url"],
        }

    final_url, search_template = _inspect_custom_opds(opds_url.strip())
    if not update_user_custom_opds(
        uid=uid,
        opds_url=final_url,
        search_template=search_template,
    ):
        raise HTTPException(status_code=500, detail="Не удалось сохранить OPDS")

    log_event(logger, request, "CUSTOM_OPDS_CHANGED", uid=uid, opds_url=final_url)
    if plain:
        return PlainTextResponse(f"OK\t0\t{quote('Другой OPDS', safe='')}\n")
    return {"status": "ok", "mode": "custom", "opds_url": final_url}


@router.patch("/users/{uid}/emails")
def set_user_emails(uid: str, data: EmailsUpdate, request: Request):
    normalized = data.emails.strip()
    if not update_user_emails(uid, normalized):
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    log_event(
        logger,
        request,
        "EMAILS_CHANGED",
        uid=uid,
        email_count=_email_count(normalized),
    )
    return {"status": "ok", "emails": normalized}


@router.patch("/users/{uid}/subject")
def set_user_subject(uid: str, data: SubjectUpdate, request: Request):
    subject = data.subject.strip() if data.subject else None
    if not update_user_subject(uid, subject):
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    log_event(
        logger,
        request,
        "SUBJECT_CHANGED",
        uid=uid,
        action="set" if subject else "cleared",
    )
    return {"status": "ok", "subject": subject}
