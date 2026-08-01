from fastapi import APIRouter
from pydantic import BaseModel
from app.services.mail import send_file #мой модуль отправки

router = APIRouter()


@router.get("/health")
def health():
    return {"status": "ok"}



class SendBookRequest(BaseModel):
    email: str
    file: str

@router.post("/send-book")
async def process_data(data: SendBookRequest):
    send_file(
        recipient_email=data.email,
        file_path=data.file,
    )

    return {
        "status": "ok"
    }