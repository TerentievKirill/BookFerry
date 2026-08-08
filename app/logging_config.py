from __future__ import annotations

import json
import logging
import re
import sys
import time
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import Request


LOG_TIMEZONE = ZoneInfo("Asia/Almaty")
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
MAX_LOG_VALUE_LENGTH = 500


class AlmatyFormatter(logging.Formatter):
    def formatTime(self, record, datefmt=None):
        moment = datetime.fromtimestamp(
            record.created,
            tz=LOG_TIMEZONE,
        )
        if datefmt:
            return moment.strftime(datefmt)
        return moment.strftime("%Y-%m-%d %H:%M:%S%z")


def configure_logging() -> None:
    """Configure BookFerry loggers without touching Uvicorn's own logging."""
    logger = logging.getLogger("bookferry")
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if any(
        getattr(handler, "_bookferry_handler", False)
        for handler in logger.handlers
    ):
        return

    handler = logging.StreamHandler(sys.stdout)
    handler._bookferry_handler = True
    handler.setFormatter(
        AlmatyFormatter(
            fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S%z",
        )
    )
    logger.addHandler(handler)


def _safe_request_id(value: str | None) -> str:
    if value and REQUEST_ID_PATTERN.fullmatch(value):
        return value
    return uuid.uuid4().hex[:12]


def request_id(request: Request) -> str:
    value = getattr(request.state, "request_id", None)
    if value:
        return str(value)
    return "-"


def _client_ip(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        value = forwarded_for.split(",", 1)[0].strip()
        if value:
            return _clean_log_value(value)

    if request.client:
        return _clean_log_value(request.client.host)

    return "-"


def _clean_log_value(value) -> str:
    text = str(value).replace("\r", " ").replace("\n", " ").strip()
    if len(text) > MAX_LOG_VALUE_LENGTH:
        return text[: MAX_LOG_VALUE_LENGTH - 3] + "..."
    return text


def _format_field(value) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(_clean_log_value(value), ensure_ascii=False)


def log_event(
    logger: logging.Logger,
    request: Request,
    event: str,
    **fields,
) -> None:
    parts = [
        f"request_id={request_id(request)}",
        event,
    ]
    parts.extend(
        f"{key}={_format_field(value)}"
        for key, value in fields.items()
    )
    logger.info(" ".join(parts))


async def request_logging_middleware(request: Request, call_next):
    logger = logging.getLogger("bookferry.access")
    current_request_id = _safe_request_id(
        request.headers.get("x-request-id")
    )
    request.state.request_id = current_request_id

    started = time.perf_counter()

    try:
        response = await call_next(request)
    except Exception:
        elapsed_ms = (time.perf_counter() - started) * 1000
        logger.exception(
            "request_id=%s HTTP method=%s path=%s status=500 "
            "duration_ms=%.1f client=%s",
            current_request_id,
            request.method,
            request.url.path,
            elapsed_ms,
            _client_ip(request),
        )
        raise

    elapsed_ms = (time.perf_counter() - started) * 1000
    response.headers["X-Request-ID"] = current_request_id

    log_method = logger.warning if response.status_code >= 400 else logger.info
    log_method(
        "request_id=%s HTTP method=%s path=%s status=%s "
        "duration_ms=%.1f client=%s",
        current_request_id,
        request.method,
        request.url.path,
        response.status_code,
        elapsed_ms,
        _client_ip(request),
    )

    return response
