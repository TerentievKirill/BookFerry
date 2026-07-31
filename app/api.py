from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
def health():
    return {"status": "ok"}


@router.post("/send-book")
def send_book():
    return {"ok": True}