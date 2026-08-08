import re
from urllib.parse import urlparse

from app.db.catalog_database import get_catalog_connection
from app.models import Book


PAGE_SIZE = 20
_PAGE_TOKEN_PREFIX = "local:"


def _page_offset(page_token: str | None) -> int:
    if page_token is None:
        return 0

    if not page_token.startswith(_PAGE_TOKEN_PREFIX):
        raise ValueError("Некорректная страница поиска")

    raw_offset = page_token[len(_PAGE_TOKEN_PREFIX):]

    try:
        offset = int(raw_offset)
    except ValueError as error:
        raise ValueError("Некорректная страница поиска") from error

    if offset < 0 or offset % PAGE_SIZE != 0:
        raise ValueError("Некорректная страница поиска")

    return offset


def _fts_query(query: str) -> str | None:
    words = [
        word.strip("_")
        for word in re.findall(r"\w+", query, flags=re.UNICODE)
    ]
    words = [word for word in words if word]

    if not words:
        return None

    return " AND ".join(
        f'"{word.replace(chr(34), chr(34) * 2)}"*'
        for word in words
    )


def _origin(base_url: str) -> tuple[str, str]:
    parsed = urlparse(base_url)

    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Некорректный адрес каталога")

    return parsed.scheme, parsed.netloc


def _flibusta_epub_url(base_url: str, external_id: str) -> str:
    scheme, netloc = _origin(base_url)
    return f"{scheme}://{netloc}/b/{external_id}/epub"


def _gutenberg_epub_url(base_url: str, external_id: str) -> str:
    if not external_id.isdigit():
        raise ValueError("Некорректный ID Project Gutenberg")

    scheme, netloc = _origin(base_url)
    return f"{scheme}://{netloc}/ebooks/{external_id}.epub3.images"


def _anarchist_epub_url(base_url: str, external_id: str) -> str:
    scheme, netloc = _origin(base_url)

    if "/" in external_id or not external_id:
        raise ValueError("Некорректный ID The Anarchist Library")

    return f"{scheme}://{netloc}/library/{external_id}.epub"


def _download_url(
    catalog_code: str,
    base_url: str,
    external_id: str,
) -> str:
    if catalog_code == "flibusta":
        return _flibusta_epub_url(base_url, external_id)

    if catalog_code == "gutenberg":
        return _gutenberg_epub_url(base_url, external_id)

    if catalog_code == "anarchist":
        return _anarchist_epub_url(base_url, external_id)

    raise ValueError(f"Скачивание из каталога {catalog_code} пока не поддерживается")


def search_local_catalog(
    catalog_code: str,
    base_url: str,
    query: str,
    page_token: str | None = None,
) -> tuple[list[Book], str | None]:
    offset = _page_offset(page_token)
    match_query = _fts_query(query)

    if match_query is None:
        return [], None

    with get_catalog_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                books.external_id,
                books.title,
                COALESCE(books.author, '') AS author
            FROM books_fts
            JOIN books ON books.id = books_fts.rowid
            WHERE books_fts MATCH ?
              AND books.catalog_code = ?
            ORDER BY bm25(books_fts), books.title COLLATE NOCASE
            LIMIT ? OFFSET ?
            """,
            (
                match_query,
                catalog_code,
                PAGE_SIZE + 1,
                offset,
            ),
        ).fetchall()

    has_more = len(rows) > PAGE_SIZE
    rows = rows[:PAGE_SIZE]

    books = [
        Book(
            author=row["author"],
            title=row["title"],
            url=_download_url(
                catalog_code=catalog_code,
                base_url=base_url,
                external_id=row["external_id"],
            ),
        )
        for row in rows
    ]

    next_page_token = (
        f"{_PAGE_TOKEN_PREFIX}{offset + PAGE_SIZE}"
        if has_more
        else None
    )

    return books, next_page_token
