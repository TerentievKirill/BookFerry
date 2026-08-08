import logging
import os
import sqlite3

import requests
from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from app.db.catalogs import get_catalog, get_catalogs
from app.db.users import (
    create_user,
    get_user,
    get_user_by_uid,
    register_user,
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
    Catalog,
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
from app.services.download import download_book, remove_book
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
    return len(
        [item for item in value.split(",") if item.strip()]
    )


@router.get("/health")
def health():
    return {"status": "ok"}


def _active_catalog(catalog_id: int):
    catalog = get_catalog(catalog_id)
    if catalog is None or not catalog["enabled"]:
        raise HTTPException(
            status_code=404,
            detail="Активный каталог не найден",
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


def _inspect_custom_opds(opds_url: str) -> tuple[str, str]:
    try:
        return inspect_opds(opds_url)
    except requests.RequestException as error:
        raise HTTPException(
            status_code=502,
            detail=f"Не удалось открыть OPDS: {error}",
        ) from error
    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error),
        ) from error


@router.post(
    "/search",
    response_model=SearchResponse,
)
def search(data: SearchRequest, request: Request):
    log_event(
        logger,
        request,
        "SEARCH",
        telegram_id=data.telegram_id,
        query=data.query,
        page=data.page_url or "first",
    )

    user = get_user(data.telegram_id)

    if user is None:
        log_event(
            logger,
            request,
            "SEARCH_ERROR",
            level=logging.WARNING,
            telegram_id=data.telegram_id,
            query=data.query,
            error="user_not_found",
        )
        raise HTTPException(
            status_code=404,
            detail="Пользователь не найден",
        )

    source = "unknown"

    try:
        if user["custom_opds_url"]:
            source = "custom_opds"
            source_url = user["custom_opds_url"]
            books, next_page_url = search_opds(
                url=user["custom_opds_url"],
                query=data.query,
                page_url=data.page_url,
                search_template=user["custom_opds_search_template"],
            )
        else:
            catalog = _active_catalog(user["catalog_id"])
            source = catalog["code"]
            source_url = catalog["base_url"]
            books, next_page_url = search_local_catalog(
                catalog_code=catalog["code"],
                base_url=catalog["base_url"],
                query=data.query,
                page_token=data.page_url,
            )
    except requests.RequestException as error:
        log_event(
            logger,
            request,
            "SEARCH_ERROR",
            level=logging.WARNING,
            telegram_id=data.telegram_id,
            source=source,
            query=data.query,
            error=str(error),
        )
        raise HTTPException(
            status_code=502,
            detail=f"OPDS-каталог недоступен: {error}",
        ) from error
    except ValueError as error:
        log_event(
            logger,
            request,
            "SEARCH_ERROR",
            level=logging.WARNING,
            telegram_id=data.telegram_id,
            source=source,
            query=data.query,
            error=str(error),
        )
        raise HTTPException(
            status_code=400,
            detail=str(error),
        ) from error

    log_event(
        logger,
        request,
        "SEARCH_RESULT",
        telegram_id=data.telegram_id,
        source=source,
        source_url=source_url,
        query=data.query,
        found=len(books),
        next_page=next_page_url,
        sample=_books_sample(books),
    )

    return SearchResponse(
        books=books,
        next_page_url=next_page_url,
    )


@router.post("/send-book")
def process_data(data: SendBookRequest, request: Request):
    log_event(
        logger,
        request,
        "SEND_BOOK",
        telegram_id=data.telegram_id,
        url=data.url,
    )

    user = get_user(data.telegram_id)

    if user is None:
        log_event(
            logger,
            request,
            "SEND_BOOK_ERROR",
            level=logging.WARNING,
            telegram_id=data.telegram_id,
            error="user_not_found",
        )
        raise HTTPException(
            status_code=404,
            detail="Пользователь не найден",
        )

    if not user["emails"]:
        log_event(
            logger,
            request,
            "SEND_BOOK_ERROR",
            level=logging.WARNING,
            telegram_id=data.telegram_id,
            error="email_not_configured",
        )
        raise HTTPException(
            status_code=400,
            detail="У пользователя не указан email",
        )

    try:
        path = download_book(data.url)
    except requests.RequestException as error:
        log_event(
            logger,
            request,
            "SEND_BOOK_ERROR",
            level=logging.WARNING,
            telegram_id=data.telegram_id,
            url=data.url,
            error=str(error),
        )
        raise HTTPException(
            status_code=502,
            detail=f"Не удалось скачать книгу: {error}",
        ) from error
    except ValueError as error:
        log_event(
            logger,
            request,
            "SEND_BOOK_ERROR",
            level=logging.WARNING,
            telegram_id=data.telegram_id,
            url=data.url,
            error=str(error),
        )
        raise HTTPException(
            status_code=400,
            detail=str(error),
        ) from error

    emails = [
        email.strip()
        for email in user["emails"].split(",")
        if email.strip()
    ]

    try:
        for email in emails:
            send_file(
                recipient_email=email,
                file_path=path,
            )

        log_event(
            logger,
            request,
            "SEND_BOOK_RESULT",
            telegram_id=data.telegram_id,
            filename=os.path.basename(path),
            email_count=len(emails),
            result="success",
        )

        return FileResponse(
            path=path,
            filename=os.path.basename(path),
            media_type="application/octet-stream",
            background=BackgroundTask(
                remove_book,
                path,
            ),
        )

    except Exception as error:
        log_event(
            logger,
            request,
            "SEND_BOOK_ERROR",
            level=logging.ERROR,
            telegram_id=data.telegram_id,
            filename=os.path.basename(path),
            email_count=len(emails),
            error=str(error),
        )
        remove_book(path)
        raise


@router.get(
    "/users/telegram/{telegram_id}",
    response_model=TelegramUser,
)
def get_telegram_user(telegram_id: int, request: Request):
    user = get_user(telegram_id)

    if user is None:
        log_event(
            logger,
            request,
            "PROFILE_READ",
            level=logging.WARNING,
            telegram_id=telegram_id,
            result="not_found",
        )
        raise HTTPException(
            status_code=404,
            detail="Пользователь Telegram не найден",
        )

    log_event(
        logger,
        request,
        "PROFILE_READ",
        telegram_id=telegram_id,
        result="success",
    )

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
        log_event(
            logger,
            request,
            "USER_CREATED",
            telegram_id=telegram_id,
            client_type="telegram",
        )

    builtin = _catalog_by_base_url(opds_url)
    if builtin is not None:
        update_telegram_catalog(telegram_id, builtin["id"])
        log_event(
            logger,
            request,
            "CATALOG_CHANGED",
            telegram_id=telegram_id,
            catalog_id=builtin["id"],
            catalog_code=builtin["code"],
            catalog_name=builtin["name"],
        )
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
        raise HTTPException(
            status_code=500,
            detail="Не удалось сохранить пользовательский OPDS",
        )

    log_event(
        logger,
        request,
        "CUSTOM_OPDS_CHANGED",
        telegram_id=telegram_id,
        opds_url=final_url,
    )

    return {
        "status": "ok",
        "mode": "custom",
        "opds_url": final_url,
    }


@router.patch("/users/telegram/{telegram_id}/catalog")
def set_telegram_user_catalog(
    telegram_id: int,
    data: CatalogUpdate,
    request: Request,
):
    if get_user(telegram_id) is None:
        create_user(telegram_id)
        log_event(
            logger,
            request,
            "USER_CREATED",
            telegram_id=telegram_id,
            client_type="telegram",
        )

    catalog = _active_catalog(data.catalog_id)
    update_telegram_catalog(telegram_id, catalog["id"])

    log_event(
        logger,
        request,
        "CATALOG_CHANGED",
        telegram_id=telegram_id,
        catalog_id=catalog["id"],
        catalog_code=catalog["code"],
        catalog_name=catalog["name"],
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
        raise HTTPException(
            status_code=404,
            detail="Пользователь Telegram не найден",
        )

    normalized_emails = emails.strip()
    updated = update_email(
        telegram_id=telegram_id,
        emails=normalized_emails,
    )

    if not updated:
        raise HTTPException(
            status_code=500,
            detail="Не удалось сохранить email",
        )

    log_event(
        logger,
        request,
        "EMAILS_CHANGED",
        telegram_id=telegram_id,
        email_count=_email_count(normalized_emails),
    )

    return {
        "status": "ok",
        "emails": normalized_emails,
    }


@router.patch("/users/telegram/{telegram_id}/subject")
def set_telegram_user_subject(
    telegram_id: int,
    request: Request,
    subject: str | None = Body(
        default=None,
        embed=True,
    ),
):
    if get_user(telegram_id) is None:
        raise HTTPException(
            status_code=404,
            detail="Пользователь Telegram не найден",
        )

    normalized_subject = (
        subject.strip()
        if subject
        else None
    )

    updated = update_subject(
        telegram_id=telegram_id,
        subject=normalized_subject,
    )

    if not updated:
        raise HTTPException(
            status_code=500,
            detail="Не удалось сохранить тему письма",
        )

    log_event(
        logger,
        request,
        "SUBJECT_CHANGED",
        telegram_id=telegram_id,
        action="set" if normalized_subject else "cleared",
    )

    return {
        "status": "ok",
        "subject": normalized_subject,
    }


@router.get("/catalogs", response_model=list[Catalog])
def list_catalogs():
    return [dict(catalog) for catalog in get_catalogs()]


@router.post("/users/register", response_model=User, status_code=201)
def create_generic_user(data: RegisterUserRequest, request: Request):
    try:
        user = register_user(data.client_type, data.external_id)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except sqlite3.IntegrityError as error:
        raise HTTPException(
            status_code=409,
            detail="Пользователь уже существует",
        ) from error

    log_event(
        logger,
        request,
        "USER_REGISTERED",
        uid=user["uid"],
        client_type=data.client_type,
        external_id=data.external_id,
    )

    return User(**dict(user))


@router.get("/users/{uid}", response_model=User)
def get_generic_user(uid: str, request: Request):
    user = get_user_by_uid(uid)
    if user is None:
        log_event(
            logger,
            request,
            "PROFILE_READ",
            level=logging.WARNING,
            uid=uid,
            result="not_found",
        )
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    log_event(
        logger,
        request,
        "PROFILE_READ",
        uid=uid,
        result="success",
    )
    return User(**dict(user))


@router.patch("/users/{uid}/catalog")
def set_user_catalog(uid: str, data: CatalogUpdate, request: Request):
    if get_user_by_uid(uid) is None:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    catalog = _active_catalog(data.catalog_id)
    update_user_catalog(uid, catalog["id"])

    log_event(
        logger,
        request,
        "CATALOG_CHANGED",
        uid=uid,
        catalog_id=catalog["id"],
        catalog_code=catalog["code"],
        catalog_name=catalog["name"],
    )

    return {
        "status": "ok",
        "catalog_id": catalog["id"],
        "opds_url": catalog["base_url"],
    }


@router.patch("/users/{uid}/opds")
def set_user_opds(uid: str, data: OpdsUpdate, request: Request):
    if get_user_by_uid(uid) is None:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    builtin = _catalog_by_base_url(data.opds_url)
    if builtin is not None:
        update_user_catalog(uid, builtin["id"])
        log_event(
            logger,
            request,
            "CATALOG_CHANGED",
            uid=uid,
            catalog_id=builtin["id"],
            catalog_code=builtin["code"],
            catalog_name=builtin["name"],
        )
        return {
            "status": "ok",
            "mode": "catalog",
            "catalog_id": builtin["id"],
            "opds_url": builtin["base_url"],
        }

    final_url, search_template = _inspect_custom_opds(data.opds_url.strip())

    if not update_user_custom_opds(
        uid=uid,
        opds_url=final_url,
        search_template=search_template,
    ):
        raise HTTPException(
            status_code=500,
            detail="Не удалось сохранить пользовательский OPDS",
        )

    log_event(
        logger,
        request,
        "CUSTOM_OPDS_CHANGED",
        uid=uid,
        opds_url=final_url,
    )

    return {
        "status": "ok",
        "mode": "custom",
        "opds_url": final_url,
    }


@router.patch("/users/{uid}/emails")
def set_user_emails(uid: str, data: EmailsUpdate, request: Request):
    normalized_emails = data.emails.strip()
    if not update_user_emails(uid, normalized_emails):
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    log_event(
        logger,
        request,
        "EMAILS_CHANGED",
        uid=uid,
        email_count=_email_count(normalized_emails),
    )

    return {"status": "ok", "emails": normalized_emails}


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
