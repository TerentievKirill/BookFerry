import os
import re
from urllib.parse import unquote, urlparse

import requests


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
                return filename

    final_name = unquote(os.path.basename(urlparse(response.url).path))

    if final_name.lower().endswith(".epub"):
        return final_name

    if final_name:
        return f"{final_name}.epub"

    return "book.epub"


def download_book(url: str) -> str:
    response = requests.get(url, timeout=30)
    response.raise_for_status()

    temp_dir = os.path.join(os.getcwd(), "Temp")
    os.makedirs(temp_dir, exist_ok=True)

    filename = _filename_from_response(response)
    path = os.path.join(temp_dir, filename)

    with open(path, "wb") as file:
        file.write(response.content)

    return path


def remove_book(path):
    if os.path.exists(path):
        os.remove(path)
