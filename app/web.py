from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse


router = APIRouter(include_in_schema=False)
WEB_INDEX = Path(__file__).resolve().parent.parent / "web" / "index.html"


@router.get("/")
def index():
    return FileResponse(WEB_INDEX)
