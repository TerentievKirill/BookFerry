from pydantic import BaseModel

class SearchRequest(BaseModel):
    telegram_id: int
    query: str


class SendBookRequest(BaseModel):
    telegram_id: int
    url: str

class Book(BaseModel):
    author: str
    title: str
    url: str



class TelegramUser(BaseModel):
    id: int
    telegram_id: int
    opds_url: str
    emails: str | None = None
    subject: str | None = None
