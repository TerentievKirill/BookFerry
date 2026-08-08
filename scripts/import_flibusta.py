from __future__ import annotations

import argparse
import gzip
import os
import sqlite3
import sys
from pathlib import Path
from typing import Iterator


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import CATALOG_DB_NAME
from app.db.catalog_database import create_catalog_schema


BATCH_SIZE = 5000
PROGRESS_STEP = 100000


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


def _parse_value(raw_value: str):
    value = raw_value.strip()

    if value.upper() == "NULL":
        return None

    if len(value) >= 2 and value[0] == "'" and value[-1] == "'":
        return _mysql_unescape(value[1:-1])

    return value


def _split_fields(row: str) -> list:
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
            fields.append(_parse_value(row[start:index]))
            start = index + 1

    fields.append(_parse_value(row[start:]))
    return fields


def _iter_tuple_strings(values: str) -> Iterator[str]:
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


def iter_mysql_rows(path: Path, table: str) -> Iterator[list]:
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

            for raw_row in _iter_tuple_strings(values):
                yield _split_fields(raw_row)


def _flush_batch(
    conn: sqlite3.Connection,
    sql: str,
    batch: list[tuple],
) -> None:
    if not batch:
        return

    conn.executemany(sql, batch)
    batch.clear()


def _author_name(row: list) -> str:
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


def import_authors(
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

    for row in iter_mysql_rows(path, "libavtorname"):
        if len(row) < 5:
            continue

        batch.append((int(row[0]), _author_name(row)))
        count += 1

        if len(batch) >= BATCH_SIZE:
            _flush_batch(conn, sql, batch)

        if count % PROGRESS_STEP == 0:
            print(f"Авторы: {count:,}")

    _flush_batch(conn, sql, batch)
    print(f"Авторы загружены: {count:,}")
    return count


def import_author_links(
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

    for row in iter_mysql_rows(path, "libavtor"):
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


def import_books(
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

    for row in iter_mysql_rows(path, "libbook"):
        read_count += 1

        if len(row) < 12:
            continue

        file_type = str(row[8] or "").strip().lower()
        deleted = str(row[11] or "").strip()

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


def fill_book_authors(conn: sqlite3.Connection) -> None:
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
                WHERE flibusta_book_authors.book_id = CAST(books.external_id AS INTEGER)
            ),
            ''
        )
        WHERE catalog_code = 'flibusta'
        """
    )

    print("Авторы книг собраны")


def rebuild_fts(conn: sqlite3.Connection) -> None:
    print("Строю FTS5 индекс...")
    conn.execute(
        """
        INSERT INTO books_fts(books_fts)
        VALUES ('rebuild')
        """
    )
    conn.execute("ANALYZE")
    print("FTS5 индекс готов")


def build_catalog(
    sql_dir: Path,
    catalog_db: Path,
) -> None:
    book_dump = sql_dir / "lib.libbook.sql.gz"
    author_link_dump = sql_dir / "lib.libavtor.sql.gz"
    author_dump = sql_dir / "lib.libavtorname.sql.gz"

    for path in (book_dump, author_link_dump, author_dump):
        if not path.is_file():
            raise FileNotFoundError(f"Не найден файл: {path}")

    catalog_db.parent.mkdir(parents=True, exist_ok=True)
    temp_db = catalog_db.with_name(f"{catalog_db.name}.new")

    if temp_db.exists():
        temp_db.unlink()

    conn = sqlite3.connect(temp_db)

    try:
        conn.execute("PRAGMA journal_mode = OFF")
        conn.execute("PRAGMA synchronous = OFF")
        conn.execute("PRAGMA temp_store = FILE")
        create_catalog_schema(conn)

        import_authors(conn, author_dump)
        conn.commit()

        import_author_links(conn, author_link_dump)
        conn.commit()

        import_books(conn, book_dump)
        conn.commit()

        fill_book_authors(conn)
        conn.commit()

        rebuild_fts(conn)
        conn.commit()

        books_count = conn.execute(
            "SELECT COUNT(*) FROM books WHERE catalog_code = 'flibusta'"
        ).fetchone()[0]

        print(f"Итого книг Flibusta: {books_count:,}")

    except Exception:
        conn.close()
        if temp_db.exists():
            temp_db.unlink()
        raise
    else:
        conn.close()

    os.replace(temp_db, catalog_db)
    print(f"Готовая база установлена: {catalog_db}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Импорт метаданных Flibusta в локальный каталог BookFerry"
    )
    parser.add_argument(
        "--sql-dir",
        default="/opt/data/flibusta_sql",
        help="Каталог с lib.libbook/lib.libavtor/lib.libavtorname .sql.gz",
    )
    parser.add_argument(
        "--catalog-db",
        default=CATALOG_DB_NAME,
        help="Путь к catalog.db",
    )
    args = parser.parse_args()

    build_catalog(
        sql_dir=Path(args.sql_dir),
        catalog_db=Path(args.catalog_db),
    )


if __name__ == "__main__":
    main()
