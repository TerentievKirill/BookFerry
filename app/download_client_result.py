import logging

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from app.db.users import get_user_by_uid, touch_user
from app.logging_config import log_event


router = APIRouter()
logger = logging.getLogger("bookferry.api")


@router.get("/download/client-result", response_class=PlainTextResponse)
def download_client_result(
    request: Request,
    uid: str = Query(..., min_length=1, max_length=64),
    status: str = Query(..., min_length=1, max_length=16),
    bytes_received: int = Query(0, alias="bytes", ge=0),
    attempts: int = Query(1, ge=1, le=5),
    duration_ms: int = Query(0, ge=0),
    http_status: int = Query(0),
    net_status: int = Query(0),
    title: str | None = Query(None, max_length=300),
    error: str | None = Query(None, max_length=200),
):
    user = get_user_by_uid(uid)
    if user is None:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    if user["client_type"] != "pocketbook":
        raise HTTPException(
            status_code=400,
            detail="Результат загрузки принимается только от PocketBook",
        )

    result = status.strip().lower()
    if result not in {"success", "error"}:
        raise HTTPException(
            status_code=400,
            detail="status должен быть success или error",
        )

    touch_user(uid)

    log_event(
        logger,
        request,
        "DOWNLOAD_CLIENT_RESULT",
        level=logging.INFO if result == "success" else logging.WARNING,
        uid=user["uid"],
        client_type=user["client_type"],
        result=result,
        title=title or "-",
        bytes=bytes_received,
        attempts=attempts,
        duration_ms=duration_ms,
        http_status=http_status,
        net_status=net_status,
        error=error or "-",
    )

    return PlainTextResponse("OK\n")
