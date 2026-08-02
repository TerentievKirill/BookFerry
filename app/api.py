from fastapi import APIRouter
from typing import List

from app.models import  SearchRequest, SendBookRequest
from app.services.opds import search_opds, Book
from app.services.book_delivery import deliver_book


router = APIRouter()


@router.get("/health")
def health():
    return {"status": "ok"}



@router.post("/search", response_model=List[Book])
async def search(data: SearchRequest):
    return search_opds(
        DEFAULT_OPDS_URL,
        data.query,
    )


@router.post("/send-book")
async def process_data(data: SendBookRequest):
    deliver_book(
        recipient_email=data.email,
        book=data.book,
    )

    return {
        "status": "ok"
    }

