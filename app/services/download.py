import os
import re
import tempfile
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
            filename = unquote(match.group(1).strip().strip('"'))
            if filename:
                return os.path.basename(filename)

    final_name = unquote(os.path.basename(urlparse(response.url).path))

    if final_name.lower().endswith(".epub"):
        return final_name

    if final_name:
        return f"{final_name}.epub"

    return "book.epub"


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

    temp_root = os.path.join(os.getcwd(), "Temp")
    os.makedirs(temp_root, exist_ok=True)

    request_dir = tempfile.mkdtemp(prefix="download_", dir=temp_root)
    path = os.path.join(request_dir, filename)

    try:
        with open(path, "wb") as file:
            file.write(content)
    except Exception:
        try:
            os.rmdir(request_dir)
        except OSError:
            pass
        raise

    return path


def remove_book(path):
    temp_root = os.path.abspath(os.path.join(os.getcwd(), "Temp"))
    parent_dir = os.path.abspath(os.path.dirname(path))

    if os.path.exists(path):
        os.remove(path)

    if os.path.dirname(parent_dir) == temp_root:
        try:
            os.rmdir(parent_dir)
        except OSError:
            pass
