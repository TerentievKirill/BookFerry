import logging
import smtplib
from email.message import EmailMessage
from threading import Thread

from app.config import (
    DEFAULT_SUBJECT,
    SMTP_HOST,
    SMTP_LOGIN,
    SMTP_PASSWORD,
    SMTP_PORT,
)


logger = logging.getLogger("bookferry.mail")


def send_file(
    recipient_email: str,
    file_content: bytes,
    filename: str,
    subject: str | None = None,
):
    msg = EmailMessage()
    msg["Subject"] = subject or DEFAULT_SUBJECT
    msg["From"] = SMTP_LOGIN
    msg["To"] = recipient_email
    msg.set_content("")
    msg.add_attachment(
        file_content,
        maintype="application",
        subtype="octet-stream",
        filename=filename,
    )

    def deliver():
        try:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
                server.starttls()
                server.login(SMTP_LOGIN, SMTP_PASSWORD)
                server.send_message(msg)
        except Exception as error:
            logger.error(
                "EMAIL_SEND_ERROR recipient=%r filename=%r error=%r",
                recipient_email,
                filename,
                error,
            )

    Thread(target=deliver, daemon=True).start()
