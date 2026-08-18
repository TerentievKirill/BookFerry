from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


ClientType = Literal["telegram", "pocketbook", "flutter"]


class User(BaseModel):
    uid: str
    client_type: ClientType
    external_id: str | None = None
    catalog_id: int
    opds_url: str | None = None
    emails: str | None = None
    subject: str | None = None


class TelegramUser(BaseModel):
    uid: str
    telegram_id: int
    catalog_id: int
    opds_url: str
    emails: str | None = None
    subject: str | None = None


class Catalog(BaseModel):
    id: int
    code: str
    name: str
    base_url: str


class Book(BaseModel):
    author: str
    title: str
    url: str


class SearchResponse(BaseModel):
    books: list[Book]
    next_page_url: str | None = None
