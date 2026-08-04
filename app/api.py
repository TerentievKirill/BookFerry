from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from app.models import  SearchRequest, SendBookRequest, TelegramUser
from app.services.opds import search_opds, Book
from app.services.book_delivery import deliver_book
from app.config import DEFAULT_OPDS_URL
from app.services.download import download_book, remove_book
from app.services.mail import send_file

from app.db.users import (
    create_user,
    get_user,
    update_email,
    update_opds,
    update_subject,
)

router = APIRouter()


@router.get("/health")
def health():
    return {"status": "ok"}



@router.post("/search", response_model=list[Book])
def search(data: SearchRequest):
    user = get_user(data.telegram_id)

    if user is None:
        raise HTTPException(
            status_code=404,
            detail="Пользователь не найден",
        )

    opds_url = user["opds_url"] or DEFAULT_OPDS_URL

    return search_opds(
        opds_url,
        data.query,
    )


@router.post("/send-book")
def process_data(data: SendBookRequest):
    path = download_book(data.book)

    try:
        emails = [
            email.strip()
            for email in data.emails.split(",")
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

def get_telegram_user(telegram_id: int):
    user = get_user(telegram_id)

    if user is None:
        raise HTTPException(
            status_code=404,
            detail="Пользователь Telegram не найден",
        )

    return TelegramUser(
        id=user["id"],
        telegram_id=user["telegram_id"],
        opds_url=user["opds_url"],
        emails=user["emails"],
        subject=user["subject"],
    )

@router.patch("/users/telegram/{telegram_id}/opds")
def set_telegram_user_opds(
    telegram_id: int,
    opds_url: str = Body(..., embed=True),
):
    # На первом шаге настройки пользователя ещё может не быть.
    if get_user(telegram_id) is None:
        create_user(telegram_id)

    updated = update_opds(
        telegram_id=telegram_id,
        opds_url=opds_url.strip(),
    )

    if not updated:
        raise HTTPException(
            status_code=500,
            detail="Не удалось сохранить OPDS-каталог",
        )

    return {
        "status": "ok",
        "opds_url": opds_url.strip(),
    }


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
    subject: str | None = Body(default=None, embed=True),
):
    if get_user(telegram_id) is None:
        raise HTTPException(
            status_code=404,
            detail="Пользователь Telegram не найден",
        )

    normalized_subject = subject.strip() if subject else None

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