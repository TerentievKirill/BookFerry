import os
import re
from urllib.parse import unquote, urlparse

import requests

from app.services.safe_http import safe_get

# Size of one chunk when a book is streamed to the client.
# 64 KiB is small enough to avoid keeping the whole file in memory.
STREAM_CHUNK_SIZE = 64 * 1024


def _filename_from_response(response: requests.Response) -> str:
    # Get the filename provided by the source server.
    # Many book servers send it in the Content-Disposition header.
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
    # Decode URL-encoded names and keep only the filename itself.
    # basename() prevents a remote server from supplying a path.
    filename = unquote(os.path.basename(urlparse(response.url).path))
    if filename:
        return filename

    raise ValueError("The server did not provide a filename")


def open_book_stream(url: str) -> tuple[requests.Response, str]:
    # Open the remote file without downloading the whole EPUB yet.
    # The response stays open and will be consumed chunk by chunk later.
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
    # Yield the EPUB piece by piece instead of loading it into memory.
    try:
        for chunk in response.iter_content(chunk_size=STREAM_CHUNK_SIZE):
            if chunk:
                yield chunk
    # The upstream connection must be closed even if the client disconnects.
    finally:
        response.close()


def download_book(url: str) -> tuple[bytes, str]:
    # Telegram and e-mail delivery need the complete file in memory,
    # so this path downloads all bytes before returning
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

    return content, filename
