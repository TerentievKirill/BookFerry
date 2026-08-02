from app.services.download import download_book, remove_book
from app.services.mail import send_file
from app.services.opds import Book


def deliver_book(
    recipient_email: str,
    book: Book,
) -> None:
    path = download_book(book)

    try:
        send_file(
            recipient_email=recipient_email,
            file_path=path,
        )
    finally:
        remove_book(path)

