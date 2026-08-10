import os
import re
from urllib.parse import unquote, urlparse

import requests

from app.services.safe_http import safe_get


STREAM_CHUNK_SIZE = 64 * 1024


def _filename_from_response(response: requests.Response) -> str:
    content_disposition = response.headers.get("Content-Disposition", "")

    if content_disposition:
        match = re.search(
            r"filename\*?=(?:UTF-8''|\")?([^\";]+)",
            content_disposition,
            flags=re.IGNORECASE,
        )
        if match:
            filename = os.path.basename(
                unquote(match.group(1).strip().strip('"'))
            )
            if filename:
                return filename

    filename = unquote(os.path.basename(urlparse(response.url).path))
    if filename:
        return filename

    raise ValueError("Сервер не передал имя файла")


def open_book_stream(url: str) -> tuple[requests.Response, str]:
    response = safe_get(
        url,
        timeout=(10, 120),
        stream=True,
    )

    try:
        response.raise_for_status()
        filename = _filename_from_response(response)
    except Exception:
        response.close()
        raise

    return response, filename


def iter_book_stream(response: requests.Response):
    try:
        for chunk in response.iter_content(chunk_size=STREAM_CHUNK_SIZE):
            if chunk:
                yield chunk
    finally:
        response.close()


def download_book(url: str) -> str:
    response = safe_get(
        url,
        timeout=(10, 120),
    )

    try:
        response.raise_for_status()
        filename = _filename_from_response(response)
        content = response.content
    finally:
        response.close()

    temp_dir = os.path.join(os.getcwd(), "Temp")
    os.makedirs(temp_dir, exist_ok=True)

    path = os.path.join(temp_dir, filename)

    with open(path, "wb") as file:
        file.write(content)

    return path


def remove_book(path):
    if os.path.exists(path):
        os.remove(path)
