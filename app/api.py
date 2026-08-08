import sqlite3
import os

from fastapi import APIRouter, Body, HTTPException
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
    update_user_catalog,
    update_user_emails,
    update_user_subject,
)
from app.models import (
    Catalog,
    CatalogUpdate,
    EmailsUpdate,
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


router = APIRouter()


@router.get("/health")
def health():
    return {"status": "ok"}


@router.post(
    "/search",
    response_model=SearchResponse,
)
def search(data: SearchRequest):
    user = get_user(data.telegram_id)

    if user is None:
        raise HTTPException(
            status_code=404,
            detail="Пользователь не найден",
        )

    catalog = get_catalog(user["catalog_id"])

    if catalog is None or not catalog["enabled"]:
        raise HTTPException(
            status_code=404,
            detail="Активный каталог не найден",
        )

    try:
        books, next_page_url = search_local_catalog(
            catalog_code=catalog["code"],
            base_url=catalog["base_url"],
            query=data.query,
            page_token=data.page_url,
        )
    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error),
        ) from error

    return SearchResponse(
        books=books,
        next_page_url=next_page_url,
    )


@router.post("/send-book")
def process_data(data: SendBookRequest):
    user = get_user(data.telegram_id)

    if user is None:
        raise HTTPException(
            status_code=404,
            detail="Пользователь не найден",
        )

    if not user["emails"]:
        raise HTTPException(
            status_code=400,
            detail="У пользователя не указан email",
        )

    path = download_book(data.url)

    try:
        emails = [
            email.strip()
            for email in user["emails"].split(",")
            if email.strip()
        ]

        for email in emails:
            send_file(
                recipient_email=email,
                file_path=path,
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

    except Exception:
        remove_book(path)
        raise


@router.get(
    "/users/telegram/{telegram_id}",
    response_model=TelegramUser,
)
def get_telegram_user(telegram_id: int):
    user = get_user(telegram_id)

    if user is None:
        raise HTTPException(
            status_code=404,
            detail="Пользователь Telegram не найден",
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
    opds_url: str = Body(..., embed=True),
):
    """Legacy route: only URLs of supported catalogs are accepted."""
    catalog = next(
        (item for item in get_catalogs() if item["base_url"] == opds_url.strip()),
        None,
    )
    if catalog is None:
        raise HTTPException(status_code=400, detail="Каталог не поддерживается")
    if get_user(telegram_id) is None:
        create_user(telegram_id)
    update_telegram_catalog(telegram_id, catalog["id"])
    return {"status": "ok", "opds_url": catalog["base_url"]}


@router.patch("/users/telegram/{telegram_id}/catalog")
def set_telegram_user_catalog(telegram_id: int, data: CatalogUpdate):
    if get_user(telegram_id) is None:
        raise HTTPException(status_code=404, detail="Пользователь Telegram не найден")
    catalog = _active_catalog(data.catalog_id)
    update_telegram_catalog(telegram_id, catalog["id"])
    return {"status": "ok", "catalog_id": catalog["id"]}


@router.patch("/users/telegram/{telegram_id}/emails")
def set_telegram_user_emails(
    telegram_id: int,
    emails: str = Body(..., embed=True),
):
    if get_user(telegram_id) is None:
        raise HTTPException(
            status_code=404,
            detail="Пользователь Telegram не найден",
        )

    updated = update_email(
        telegram_id=telegram_id,
        emails=emails.strip(),
    )

    if not updated:
        raise HTTPException(
            status_code=500,
            detail="Не удалось сохранить email",
        )

    return {
        "status": "ok",
        "emails": emails.strip(),
    }


@router.patch("/users/telegram/{telegram_id}/subject")
def set_telegram_user_subject(
    telegram_id: int,
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

    return {
        "status": "ok",
        "subject": normalized_subject,
    }


def _active_catalog(catalog_id: int):
    catalog = get_catalog(catalog_id)
    if catalog is None or not catalog["enabled"]:
        raise HTTPException(status_code=404, detail="Активный каталог не найден")
    return catalog


@router.get("/catalogs", response_model=list[Catalog])
def list_catalogs():
    return [dict(catalog) for catalog in get_catalogs()]


@router.post("/users/register", response_model=User, status_code=201)
def create_generic_user(data: RegisterUserRequest):
    try:
        user = register_user(data.client_type, data.external_id)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except sqlite3.IntegrityError as error:
        raise HTTPException(status_code=409, detail="Пользователь уже существует") from error
    return User(**dict(user))


@router.get("/users/{uid}", response_model=User)
def get_generic_user(uid: str):
    user = get_user_by_uid(uid)
    if user is None:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    return User(**dict(user))


@router.patch("/users/{uid}/catalog")
def set_user_catalog(uid: str, data: CatalogUpdate):
    if get_user_by_uid(uid) is None:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    catalog = _active_catalog(data.catalog_id)
    update_user_catalog(uid, catalog["id"])
    return {"status": "ok", "catalog_id": catalog["id"]}


@router.patch("/users/{uid}/emails")
def set_user_emails(uid: str, data: EmailsUpdate):
    if not update_user_emails(uid, data.emails.strip()):
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    return {"status": "ok", "emails": data.emails.strip()}


@router.patch("/users/{uid}/subject")
def set_user_subject(uid: str, data: SubjectUpdate):
    subject = data.subject.strip() if data.subject else None
    if not update_user_subject(uid, subject):
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    return {"status": "ok", "subject": subject}
