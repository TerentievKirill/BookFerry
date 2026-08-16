import re
from urllib.parse import urlparse

from app.db.catalog_database import get_catalog_connection
from app.models import Book

# Number of books returned on one search page.
PAGE_SIZE = 20
# Local search uses offsets instead of real OPDS "next page" URLs.
# The prefix makes it clear that values like "local:20" belong to the local index.
_PAGE_TOKEN_PREFIX = "local:"


def _page_offset(page_token: str | None) -> int:
    # No token means the first page.
    if page_token is None:
        return 0
    # Do not accept page tokens created by another search source.
    if not page_token.startswith(_PAGE_TOKEN_PREFIX):
        raise ValueError("Invalid search page")
    # "local:40" -> 40
    raw_offset = page_token[len(_PAGE_TOKEN_PREFIX):]

    try:
        offset = int(raw_offset)
    except ValueError as error:
        raise ValueError("Invalid search page") from error

    # Only valid page boundaries are allowed: 0, 20, 40, 60..
    if offset < 0 or offset % PAGE_SIZE != 0:
        raise ValueError("Invalid search page")

    return offset


def _fts_query(query: str) -> str | None:
    # Keep only searchable words from the user's input.
    words = [
        word.strip("_")
        for word in re.findall(r"\w+", query, flags=re.UNICODE)
    ]
    words = [word for word in words if word]

    if not words:
        return None
    # SQLite FTS query:
    # "harry pot" -> "harry"* AND "pot"*
    #
    # AND requires every entered word to be present.
    # * allows matching by the beginning of a word.
    return " AND ".join(
        f'"{word.replace(chr(34), chr(34) * 2)}"*'
        for word in words
    )


def _origin(base_url: str) -> tuple[str, str]:
    # We only need the protocol and host to build download URLs.
    parsed = urlparse(base_url)

    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Некорректный адрес каталога")

    return parsed.scheme, parsed.netloc


def _flibusta_epub_url(base_url: str, external_id: str) -> str:
    # Flibusta book IDs are stored in the local index.
    # Example: 12345 -> https://flibusta.is/b/12345/epub
    scheme, netloc = _origin(base_url)
    return f"{scheme}://{netloc}/b/{external_id}/epub"


def _gutenberg_epub_url(base_url: str, external_id: str) -> str:
    # Gutenberg uses numeric ebook IDs.
    if not external_id.isdigit():
        raise ValueError("Invalid Project Gutenberg ID")

    scheme, netloc = _origin(base_url)
    return f"{scheme}://{netloc}/ebooks/{external_id}.epub3.images"


def _anarchist_epub_url(base_url: str, external_id: str) -> str:
    scheme, netloc = _origin(base_url)
    # AmuseWiki uses a text identifier as part of the download path.
    if "/" in external_id or not external_id:
        raise ValueError("Invalid AmuseWiki ID")

    return f"{scheme}://{netloc}/library/{external_id}.epub"


def _download_url(
    catalog_code: str,
    base_url: str,
    external_id: str,
) -> str:
    # The local database stores catalog IDs, not full download URLs.
    # Each catalog has its own URL format, so we build it here.
    if catalog_code == "flibusta":
        return _flibusta_epub_url(base_url, external_id)

    if catalog_code == "gutenberg":
        return _gutenberg_epub_url(base_url, external_id)

    if catalog_code in {"anarchist", "anarchist_ru"}:
        return _anarchist_epub_url(base_url, external_id)

    raise ValueError(f"Скачивание из каталога {catalog_code} пока не поддерживается")


def search_local_catalog(
    catalog_code: str,
    base_url: str,
    query: str,
    page_token: str | None = None,
) -> tuple[list[Book], str | None]:
    # Convert the page token into an SQL OFFSET.
    offset = _page_offset(page_token)
    # Convert normal user text into a SQLite FTS query.
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
                # Read one extra row only to check whether another page exists.
                PAGE_SIZE + 1,
                offset,
            ),
        ).fetchall()

    # If we received 21 rows for a page of 20,
    # there is at least one more search result.
    has_more = len(rows) > PAGE_SIZE
    # The extra row is not returned to the client.
    rows = rows[:PAGE_SIZE]

    # Convert database rows into the same Book model
    # that is also used by external OPDS searches.
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
    # The client sends this value back when requesting the next page.
    # Example: local:20 -> local:40 -> local:60.
    next_page_token = (
        f"{_PAGE_TOKEN_PREFIX}{offset + PAGE_SIZE}"
        if has_more
        else None
    )

    return books, next_page_token
