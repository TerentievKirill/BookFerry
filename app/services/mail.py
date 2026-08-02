import smtplib
import os
from email.message import EmailMessage
from app.config import SMTP_HOST, SMTP_PORT, SMTP_LOGIN, SMTP_PASSWORD, DEFAULT_SUBJECT



def send_file(
    recipient_email: str,
    file_path: str,
):
    # 1. Создаем объект сообщения
    msg = EmailMessage()
    msg['Subject'] = DEFAULT_SUBJECT
    msg['From'] = SMTP_LOGIN
    msg['To'] = recipient_email
    msg.set_content("")
    if os.path.exists(file_path):
        with open(file_path, 'rb') as f:
            file_data = f.read()
            file_name = os.path.basename(file_path)

        # Добавляем вложение
        msg.add_attachment(
            file_data,
            maintype="application",
            subtype="octet-stream",
            filename=file_name,
        )
    else:
        print(f'Файл {file_path} не найден.')

    # 4. Отправляем письмо через SMTP-сервер
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()  # Безопасное подключение
            server.login(SMTP_LOGIN, SMTP_PASSWORD)
            server.send_message(msg)
            print('Письмо успешно отправлено!')
    except Exception as e:
        print(f'Ошибка при отправке: {e}')