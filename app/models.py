from pydantic import BaseModel

class SearchRequest(BaseModel):
    query: str

class Book(BaseModel):
    author: str
    title: str
    url: str

class SendBookRequest(BaseModel):
    email: str
    file: str
