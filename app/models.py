from typing import Literal

from pydantic import BaseModel


ClientType = Literal["telegram", "pocketbook", "flutter"]


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


class Catalog(BaseModel):
    id: int
    code: str
    name: str
    base_url: str
    enabled: bool
    sort_order: int


class User(BaseModel):
    id: int
    uid: str
    client_type: ClientType
    external_id: str | None = None
    catalog_id: int
    opds_url: str | None = None
    emails: str | None = None
    subject: str | None = None
    created_at: str
    last_seen_at: str | None = None


class TelegramUser(BaseModel):
    id: int
    uid: str
    telegram_id: int
    catalog_id: int
    opds_url: str
    emails: str | None = None
    subject: str | None = None


class RegisterUserRequest(BaseModel):
    client_type: ClientType
    external_id: str | None = None


class CatalogUpdate(BaseModel):
    catalog_id: int


class OpdsUpdate(BaseModel):
    opds_url: str


class EmailsUpdate(BaseModel):
    emails: str


class SubjectUpdate(BaseModel):
    subject: str | None = None
