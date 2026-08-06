from pydantic import BaseModel


class SearchRequest(BaseModel):
    telegram_id: int
    query: str
    page_url: str | None = None


class SendBookRequest(BaseModel):
    telegram_id: int
    url: str


class Book(BaseModel):
    author: str
    title: str
    url: str


class SearchResponse(BaseModel):
    books: list[Book]
    next_page_url: str | None = None


class TelegramUser(BaseModel):
    id: int
    telegram_id: int
    opds_url: str
    emails: str | None = None
    subject: str | None = None
