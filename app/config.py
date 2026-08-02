import os

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")

SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
SMTP_LOGIN = os.getenv("SMTP_LOGIN")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
DEFAULT_SUBJECT = os.getenv("DEFAULT_SUBJECT")

DB_NAME = os.getenv("DB_NAME")

DEFAULT_OPDS_URL = os.getenv("DEFAULT_OPDS_URL")


