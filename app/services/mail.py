import os
import smtplib
from email.message import EmailMessage

from app.config import (
    DEFAULT_SUBJECT,
    SMTP_HOST,
    SMTP_LOGIN,
    SMTP_PASSWORD,
    SMTP_PORT,
)


def send_file(
    recipient_email: str,
    file_path: str,
    subject: str | None = None,
):
    with open(file_path, "rb") as file:
        file_data = file.read()

    msg = EmailMessage()
    msg["Subject"] = subject or DEFAULT_SUBJECT
    msg["From"] = SMTP_LOGIN
    msg["To"] = recipient_email
    msg.set_content("")
    msg.add_attachment(
        file_data,
        maintype="application",
        subtype="octet-stream",
        filename=os.path.basename(file_path),
    )

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_LOGIN, SMTP_PASSWORD)
        server.send_message(msg)
