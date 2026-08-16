from __future__ import annotations

import csv
import fcntl
import gzip
import os
import sqlite3
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Iterator
from urllib.parse import urljoin, urlparse

import requests


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import CATALOG_DB_NAME
from app.db.catalog_database import create_catalog_schema


DATA_DIR = Path("/app/data")
FLIBUSTA_DIR = DATA_DIR / "flibusta_sql"
GUTENBERG_SOURCE = DATA_DIR / "gutenberg" / "pg_catalog.csv.gz"
LOCK_FILE = DATA_DIR / "catalog-update.lock"

FLIBUSTA_DUMPS = {
    "lib.libbook.sql.gz": "https://flibusta.is/sql/lib.libbook.sql.gz",
    "lib.libavtor.sql.gz": "https://flibusta.is/sql/lib.libavtor.sql.gz",
    "lib.libavtorname.sql.gz": "https://flibusta.is/sql/lib.libavtorname.sql.gz",
}

GUTENBERG_CATALOG_URL = (
    "https://www.gutenberg.org/cache/epub/feeds/pg_catalog.csv.gz"
)

ANARCHIST_EN_URL = "https://theanarchistlibrary.org/opds/titles/1"
ANARCHIST_RU_URL = "https://ru.anarchistlibraries.net/opds/titles/1"

MIN_COUNTS = {
    "flibusta": 500_000,
    "gutenberg": 50_000,
    "anarchist": 10_000,
    "anarchist_ru": 500,
}

USER_AGENT = (
    "BookFerry/1.0 "
    "(+https://github.com/TerentievKirill/BookFerry)"
)

BATCH_SIZE = 5000
AMUSEWIKI_BATCH_SIZE = 1000
PROGRESS_STEP = 100_000
MAX_OPDS_PAGES = 10_000


# ---------------------------------------------------------------------------
# Common rebuild helpers
# ---------------------------------------------------------------------------

def _new_catalog_connection(catalog_db: Path) -> tuple[sqlite3.Connection, Path]:
    # Build the new catalog separately. The production DB is replaced only
    # after every source has been imported and validated.
    catalog_db.parent.mkdir(parents=True, exist_ok=True)
    temp_db = catalog_db.with_name(f"{catalog_db.name}.update")

    if temp_db.exists():
        temp_db.unlink()

    conn = sqlite3.connect(temp_db)
    conn.execute("PRAGMA journal_mode = OFF")
    conn.execute("PRAGMA synchronous = OFF")
    conn.execute("PRAGMA temp_store = FILE")
    create_catalog_schema(conn)
    return conn, temp_db


def _finish_catalog_rebuild(
    conn: sqlite3.Connection,
    temp_db: Path,
    catalog_db: Path,
) -> None:
    print("Строю общий FTS5 индекс...")
    conn.execute(
        """
        INSERT INTO books_fts(books_fts)
        VALUES ('rebuild')
        """
    )
    conn.execute("ANALYZE")
    conn.commit()
    conn.close()

    os.replace(temp_db, catalog_db)
    print(f"Готовая база установлена: {catalog_db}")


def _abort_catalog_rebuild(
    conn: sqlite3.Connection,
    temp_db: Path,
) -> None:
    conn.close()
    if temp_db.exists():
        temp_db.unlink()


def _catalog_count(conn: sqlite3.Connection, catalog_code: str) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM books WHERE catalog_code = ?",
        (catalog_code,),
    ).fetchone()[0]


def _validate_catalog(conn: sqlite3.Connection, catalog_code: str) -> int:
    count = _catalog_count(conn, catalog_code)
    minimum = MIN_COUNTS[catalog_code]

    if count < minimum:
        raise ValueError(
            f"Каталог {catalog_code}: только {count:,} записей, "
            f"ожидалось минимум {minimum:,}. Рабочая база не будет заменена."
        )

    print(f"Проверка {catalog_code}: {count:,} записей — OK")
    return count


def _download_file(url: str, target: Path, attempts: int = 3) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(f"{target.name}.part")

    for attempt in range(1, attempts + 1):
        try:
            print(f"Скачиваю {url} -> {target}")

            with requests.get(
                url,
                stream=True,
                timeout=(15, 300),
                headers={"User-Agent": USER_AGENT},
            ) as response:
                response.raise_for_status()

                with temp.open("wb") as output:
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            output.write(chunk)

            if temp.stat().st_size == 0:
                raise ValueError(f"Пустой файл: {url}")

            os.replace(temp, target)
            print(f"Скачано: {target} ({target.stat().st_size:,} bytes)")
            return

        except Exception:
            if temp.exists():
                temp.unlink()

            if attempt >= attempts:
                raise

            delay = attempt * 5
            print(
                f"Ошибка скачивания, попытка {attempt}/{attempts}. "
                f"Повтор через {delay} сек."
            )
            time.sleep(delay)


# ---------------------------------------------------------------------------
# Flibusta
# ---------------------------------------------------------------------------

def _mysql_unescape(value: str) -> str:
    result: list[str] = []
    escape_map = {
        "0": "\0",
        "b": "\b",
        "n": "\n",
        "r": "\r",
        "t": "\t",
        "Z": "\x1a",
        "'": "'",
        '"': '"',
        "\\": "\\",
    }

    index = 0
    while index < len(value):
        char = value[index]

        if char != "\\" or index + 1 >= len(value):
            result.append(char)
            index += 1
            continue

        escaped = value[index + 1]
        result.append(escape_map.get(escaped, escaped))
        index += 2

    return "".join(result)


def _parse_mysql_value(raw_value: str):
    value = raw_value.strip()

    if value.upper() == "NULL":
        return None

    if len(value) >= 2 and value[0] == "'" and value[-1] == "'":
        return _mysql_unescape(value[1:-1])

    return value


def _split_mysql_fields(row: str) -> list:
    fields: list = []
    start = 0
    in_quote = False
    escaped = False

    for index, char in enumerate(row):
        if in_quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == "'":
                in_quote = False
            continue

        if char == "'":
            in_quote = True
        elif char == ",":
            fields.append(_parse_mysql_value(row[start:index]))
            start = index + 1

    fields.append(_parse_mysql_value(row[start:]))
    return fields


def _iter_mysql_tuple_strings(values: str) -> Iterator[str]:
    in_quote = False
    escaped = False
    depth = 0
    row_start: int | None = None

    for index, char in enumerate(values):
        if in_quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == "'":
                in_quote = False
            continue

        if char == "'":
            in_quote = True
            continue

        if char == "(":
            if depth == 0:
                row_start = index + 1
            depth += 1
            continue

        if char == ")":
            depth -= 1
            if depth == 0 and row_start is not None:
                yield values[row_start:index]
                row_start = None


def _iter_mysql_rows(path: Path, table: str) -> Iterator[list]:
    prefix = f"INSERT INTO `{table}` VALUES "

    with gzip.open(
        path,
        mode="rt",
        encoding="utf-8",
        errors="replace",
    ) as dump:
        for line in dump:
            if not line.startswith(prefix):
                continue

            values = line[len(prefix):].rstrip()
            if values.endswith(";"):
                values = values[:-1]

            for raw_row in _iter_mysql_tuple_strings(values):
                yield _split_mysql_fields(raw_row)


def _flush_batch(
    conn: sqlite3.Connection,
    sql: str,
    batch: list[tuple],
) -> None:
    if not batch:
        return

    conn.executemany(sql, batch)
    batch.clear()


def _flibusta_author_name(row: list) -> str:
    first_name = str(row[1] or "").strip()
    middle_name = str(row[2] or "").strip()
    last_name = str(row[3] or "").strip()
    nickname = str(row[4] or "").strip()

    name = " ".join(
        part
        for part in (first_name, middle_name, last_name)
        if part
    )

    return name or nickname


def _import_flibusta_authors(
    conn: sqlite3.Connection,
    path: Path,
) -> int:
    conn.execute(
        """
        CREATE TEMP TABLE flibusta_authors (
            author_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL
        )
        """
    )

    sql = """
        INSERT OR REPLACE INTO flibusta_authors (author_id, name)
        VALUES (?, ?)
    """
    batch: list[tuple] = []
    count = 0

    for row in _iter_mysql_rows(path, "libavtorname"):
        if len(row) < 5:
            continue

        batch.append((int(row[0]), _flibusta_author_name(row)))
        count += 1

        if len(batch) >= BATCH_SIZE:
            _flush_batch(conn, sql, batch)

        if count % PROGRESS_STEP == 0:
            print(f"Авторы: {count:,}")

    _flush_batch(conn, sql, batch)
    print(f"Авторы загружены: {count:,}")
    return count


def _import_flibusta_author_links(
    conn: sqlite3.Connection,
    path: Path,
) -> int:
    conn.execute(
        """
        CREATE TEMP TABLE flibusta_author_links (
            book_id INTEGER NOT NULL,
            author_id INTEGER NOT NULL,
            position INTEGER NOT NULL
        )
        """
    )

    sql = """
        INSERT INTO flibusta_author_links (
            book_id,
            author_id,
            position
        )
        VALUES (?, ?, ?)
    """
    batch: list[tuple] = []
    count = 0

    for row in _iter_mysql_rows(path, "libavtor"):
        if len(row) < 3:
            continue

        batch.append(
            (
                int(row[0]),
                int(row[1]),
                int(row[2]),
            )
        )
        count += 1

        if len(batch) >= BATCH_SIZE:
            _flush_batch(conn, sql, batch)

        if count % PROGRESS_STEP == 0:
            print(f"Связи книга-автор: {count:,}")

    _flush_batch(conn, sql, batch)
    conn.execute(
        """
        CREATE INDEX flibusta_author_links_book_idx
        ON flibusta_author_links (book_id, position)
        """
    )
    print(f"Связи книга-автор загружены: {count:,}")
    return count


def _import_flibusta_books(
    conn: sqlite3.Connection,
    path: Path,
) -> tuple[int, int]:
    sql = """
        INSERT OR IGNORE INTO books (
            catalog_code,
            external_id,
            title,
            author,
            language
        )
        VALUES ('flibusta', ?, ?, '', ?)
    """
    batch: list[tuple] = []
    read_count = 0
    imported_count = 0

    for row in _iter_mysql_rows(path, "libbook"):
        read_count += 1

        if len(row) < 12:
            continue

        file_type = str(row[8] or "").strip().lower()
        deleted = str(row[11] or "").strip()

        # Flibusta can convert FB2 books to EPUB on download.
        # Other source formats are not included in the local EPUB catalog.
        if file_type != "fb2" or deleted != "0":
            continue

        title = str(row[3] or "").strip()
        if not title:
            continue

        batch.append(
            (
                str(row[0]),
                title,
                str(row[5] or "").strip(),
            )
        )
        imported_count += 1

        if len(batch) >= BATCH_SIZE:
            _flush_batch(conn, sql, batch)

        if read_count % PROGRESS_STEP == 0:
            print(
                f"Книги прочитаны: {read_count:,}; "
                f"в индекс: {imported_count:,}"
            )

    _flush_batch(conn, sql, batch)
    print(
        f"Книги готовы: прочитано {read_count:,}, "
        f"добавлено {imported_count:,}"
    )
    return read_count, imported_count


def _fill_flibusta_book_authors(conn: sqlite3.Connection) -> None:
    print("Собираю авторов книг...")

    conn.execute(
        """
        CREATE TEMP TABLE flibusta_book_authors AS
        SELECT
            ordered.book_id,
            GROUP_CONCAT(ordered.name, ', ') AS author
        FROM (
            SELECT
                links.book_id,
                authors.name
            FROM flibusta_author_links AS links
            JOIN flibusta_authors AS authors
              ON authors.author_id = links.author_id
            WHERE authors.name <> ''
            ORDER BY links.book_id, links.position
        ) AS ordered
        GROUP BY ordered.book_id
        """
    )

    conn.execute(
        """
        CREATE UNIQUE INDEX flibusta_book_authors_book_idx
        ON flibusta_book_authors (book_id)
        """
    )

    conn.execute(
        """
        UPDATE books
        SET author = COALESCE(
            (
                SELECT flibusta_book_authors.author
                FROM flibusta_book_authors
                WHERE flibusta_book_authors.book_id =
                      CAST(books.external_id AS INTEGER)
            ),
            ''
        )
        WHERE catalog_code = 'flibusta'
        """
    )

    print("Авторы книг собраны")


def _download_flibusta_dumps() -> None:
    print("\n=== FLIBUSTA: скачивание дампов ===")
    for filename, url in FLIBUSTA_DUMPS.items():
        _download_file(url, FLIBUSTA_DIR / filename)


def _import_flibusta(conn: sqlite3.Connection) -> None:
    print("\n=== FLIBUSTA: импорт ===")

    _import_flibusta_authors(
        conn,
        FLIBUSTA_DIR / "lib.libavtorname.sql.gz",
    )
    conn.commit()

    _import_flibusta_author_links(
        conn,
        FLIBUSTA_DIR / "lib.libavtor.sql.gz",
    )
    conn.commit()

    _import_flibusta_books(
        conn,
        FLIBUSTA_DIR / "lib.libbook.sql.gz",
    )
    conn.commit()

    _fill_flibusta_book_authors(conn)
    conn.commit()

    _validate_catalog(conn, "flibusta")


# ---------------------------------------------------------------------------
# Project Gutenberg
# ---------------------------------------------------------------------------

def _gutenberg_required_columns(
    fieldnames: list[str] | None,
) -> dict[str, str]:
    if not fieldnames:
        raise ValueError("CSV Project Gutenberg не содержит заголовок")

    aliases = {
        "id": ("Text#", "Text", "EBook-No."),
        "type": ("Type",),
        "title": ("Title",),
        "language": ("Language", "Languages"),
        "authors": ("Authors", "Author"),
    }

    result: dict[str, str] = {}

    for key, candidates in aliases.items():
        column = next(
            (candidate for candidate in candidates if candidate in fieldnames),
            None,
        )
        if column is None:
            raise ValueError(
                f"В CSV Project Gutenberg нет колонки для {key}. "
                f"Колонки: {fieldnames}"
            )
        result[key] = column

    return result


def _import_gutenberg_books(
    conn: sqlite3.Connection,
    csv_gz: Path,
) -> int:
    sql = """
        INSERT OR IGNORE INTO books (
            catalog_code,
            external_id,
            title,
            author,
            language
        )
        VALUES ('gutenberg', ?, ?, ?, ?)
    """

    batch: list[tuple[str, str, str, str]] = []
    imported = 0

    with gzip.open(
        csv_gz,
        mode="rt",
        encoding="utf-8-sig",
        newline="",
        errors="replace",
    ) as source:
        reader = csv.DictReader(source)
        columns = _gutenberg_required_columns(reader.fieldnames)

        for row in reader:
            book_type = (row.get(columns["type"]) or "").strip().lower()
            if book_type != "text":
                continue

            external_id = (row.get(columns["id"]) or "").strip()
            title = (row.get(columns["title"]) or "").strip()

            if not external_id or not title:
                continue

            author = (row.get(columns["authors"]) or "").strip()
            language = (row.get(columns["language"]) or "").strip()

            batch.append((external_id, title, author, language))
            imported += 1

            if len(batch) >= BATCH_SIZE:
                conn.executemany(sql, batch)
                batch.clear()

    if batch:
        conn.executemany(sql, batch)

    print(f"Project Gutenberg: {imported:,} книг")
    return imported


def _import_gutenberg(conn: sqlite3.Connection) -> None:
    print("\n=== PROJECT GUTENBERG ===")

    _download_file(
        GUTENBERG_CATALOG_URL,
        GUTENBERG_SOURCE,
    )
    _import_gutenberg_books(conn, GUTENBERG_SOURCE)
    conn.commit()

    _validate_catalog(conn, "gutenberg")


# ---------------------------------------------------------------------------
# AmuseWiki / Anarchist libraries
# ---------------------------------------------------------------------------

def _xml_local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _xml_child_text(element: ET.Element, name: str) -> str:
    for child in element:
        if _xml_local_name(child.tag) == name:
            return (child.text or "").strip()
    return ""


def _opds_authors(entry: ET.Element) -> str:
    names: list[str] = []

    for child in entry:
        if _xml_local_name(child.tag) != "author":
            continue

        name = _xml_child_text(child, "name")
        if name:
            names.append(name)

    return ", ".join(names)


def _opds_epub_link(entry: ET.Element, page_url: str) -> str | None:
    for child in entry:
        if _xml_local_name(child.tag) != "link":
            continue

        href = (child.attrib.get("href") or "").strip()
        link_type = (child.attrib.get("type") or "").lower()

        if not href:
            continue

        if "epub" in link_type or href.lower().endswith(".epub"):
            return urljoin(page_url, href)

    return None


def _amusewiki_slug_from_epub_url(epub_url: str) -> str | None:
    path = urlparse(epub_url).path

    if not path.startswith("/library/") or not path.endswith(".epub"):
        return None

    slug = path[len("/library/"):-len(".epub")].strip("/")

    if not slug or "/" in slug:
        return None

    return slug


def _opds_next_page(root: ET.Element, page_url: str) -> str | None:
    for child in root:
        if _xml_local_name(child.tag) != "link":
            continue

        rel = (child.attrib.get("rel") or "").lower()
        href = (child.attrib.get("href") or "").strip()

        if rel == "next" and href:
            return urljoin(page_url, href)

    return None


def _fetch_opds_page(
    session: requests.Session,
    url: str,
) -> tuple[ET.Element, str]:
    with session.get(
        url,
        timeout=(15, 180),
        headers={"User-Agent": USER_AGENT},
    ) as response:
        response.raise_for_status()

        try:
            root = ET.fromstring(response.content)
        except ET.ParseError as error:
            raise ValueError(
                f"AmuseWiki вернул невалидный OPDS: {response.url}"
            ) from error

        if _xml_local_name(root.tag) != "feed":
            raise ValueError(
                f"AmuseWiki вернул не OPDS feed: {response.url}"
            )

        return root, response.url


def _import_amusewiki_books(
    conn: sqlite3.Connection,
    opds_url: str,
    catalog_code: str,
    catalog_name: str,
    default_language: str,
) -> int:
    sql = """
        INSERT OR IGNORE INTO books (
            catalog_code,
            external_id,
            title,
            author,
            language
        )
        VALUES (?, ?, ?, ?, ?)
    """

    visited: set[str] = set()
    batch: list[tuple[str, str, str, str, str]] = []
    imported = 0
    page_number = 0
    next_url: str | None = opds_url

    with requests.Session() as session:
        while next_url:
            if next_url in visited:
                raise ValueError(f"Зацикленная OPDS-пагинация: {next_url}")

            if page_number >= MAX_OPDS_PAGES:
                raise ValueError("Слишком много страниц OPDS")

            visited.add(next_url)
            page_number += 1

            root, current_url = _fetch_opds_page(session, next_url)

            for entry in root:
                if _xml_local_name(entry.tag) != "entry":
                    continue

                title = _xml_child_text(entry, "title")
                if not title:
                    continue

                epub_url = _opds_epub_link(entry, current_url)
                if not epub_url:
                    continue

                slug = _amusewiki_slug_from_epub_url(epub_url)
                if not slug:
                    continue

                author = _opds_authors(entry)
                language = (
                    _xml_child_text(entry, "language")
                    or default_language
                )

                batch.append(
                    (
                        catalog_code,
                        slug,
                        title,
                        author,
                        language,
                    )
                )
                imported += 1

                if len(batch) >= AMUSEWIKI_BATCH_SIZE:
                    conn.executemany(sql, batch)
                    batch.clear()

            if page_number % 10 == 0:
                print(
                    f"{catalog_name}: страниц {page_number}, "
                    f"текстов {imported:,}"
                )

            next_url = _opds_next_page(root, current_url)

    if batch:
        conn.executemany(sql, batch)

    print(
        f"{catalog_name}: {imported:,} текстов, "
        f"страниц OPDS: {page_number}"
    )
    return imported


def _import_anarchist_en(conn: sqlite3.Connection) -> None:
    print("\n=== THE ANARCHIST LIBRARY ===")

    _import_amusewiki_books(
        conn=conn,
        opds_url=ANARCHIST_EN_URL,
        catalog_code="anarchist",
        catalog_name="The Anarchist Library",
        default_language="en",
    )
    conn.commit()

    _validate_catalog(conn, "anarchist")


def _import_anarchist_ru(conn: sqlite3.Connection) -> None:
    print("\n=== БИБЛИОТЕКА АНАРХИЗМА ===")

    _import_amusewiki_books(
        conn=conn,
        opds_url=ANARCHIST_RU_URL,
        catalog_code="anarchist_ru",
        catalog_name="Библиотека Анархизма",
        default_language="ru",
    )
    conn.commit()

    _validate_catalog(conn, "anarchist_ru")


# ---------------------------------------------------------------------------
# Full catalog update
# ---------------------------------------------------------------------------

def update_all_catalogs(catalog_db: Path) -> None:
    started = time.monotonic()

    _download_flibusta_dumps()

    conn, temp_db = _new_catalog_connection(catalog_db)

    try:
        _import_flibusta(conn)
        _import_gutenberg(conn)
        _import_anarchist_en(conn)
        _import_anarchist_ru(conn)

        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise ValueError(f"SQLite integrity_check: {integrity}")

        total = conn.execute("SELECT COUNT(*) FROM books").fetchone()[0]
        print(f"\nВсего записей перед установкой: {total:,}")

        _finish_catalog_rebuild(conn, temp_db, catalog_db)

    except Exception:
        _abort_catalog_rebuild(conn, temp_db)
        raise

    elapsed = time.monotonic() - started
    print(f"Полное обновление завершено за {elapsed / 60:.1f} мин.")


def main() -> None:
    catalog_db = Path(CATALOG_DB_NAME)
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)

    # Only one full rebuild may run at a time.
    with LOCK_FILE.open("w") as lock:
        try:
            fcntl.flock(
                lock.fileno(),
                fcntl.LOCK_EX | fcntl.LOCK_NB,
            )
        except BlockingIOError:
            print(
                "Обновление каталогов уже выполняется. "
                "Новый запуск пропущен."
            )
            return

        lock.write(str(os.getpid()))
        lock.flush()

        update_all_catalogs(catalog_db)


if __name__ == "__main__":
    main()