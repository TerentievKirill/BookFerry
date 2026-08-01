import smtplib
import os
from email.message import EmailMessage

# Настройки вашего почтового сервера
SMTP_SERVER = 'smtp.gmail.com'
SMTP_PORT = 587
SENDER_EMAIL = 'kirillterentiev@gmail.com'
SENDER_PASSWORD = 'weqg srxu jdlk fvvg'  # Пароль приложения (не от почты!)
RECEIVER_EMAIL = 'kirillterentiev@gmail.com'



def send_file(
    recipient_email: str,
    file_path: str,
):
    print("start")
    # 1. Создаем объект сообщения
    msg = EmailMessage()
    msg['Subject'] = 'книга'
    msg['From'] = SENDER_EMAIL
    msg['To'] = recipient_email
    msg.set_content("")
    if os.path.exists(file_path):
        with open(file_path, 'rb') as f:
            file_data = f.read()
            file_name = os.path.basename(file_path)

        # Добавляем вложение (для PDF, картинок или бинарных файлов)
        msg.add_attachment(file_data, maintype='application', subtype='pdf', filename=file_name)
    else:
        print(f'Файл {file_path} не найден.')

    # 4. Отправляем письмо через SMTP-сервер
    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()  # Безопасное подключение
            server.login(SENDER_EMAIL, SENDER_PASSWORD)
            server.send_message(msg)
            print('Письмо успешно отправлено!')
    except Exception as e:
        print(f'Ошибка при отправке: {e}')