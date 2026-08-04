from pydantic import BaseModel

class SearchRequest(BaseModel):
    query: str

class Book(BaseModel):
    author: str
    title: str
    url: str

class SendBookRequest(BaseModel):
    emails: str
    book: Book

class TelegramUser(BaseModel):
    id: int
    telegram_id: str
    opds_url: str
    emails: str
    subject: str | None = None
