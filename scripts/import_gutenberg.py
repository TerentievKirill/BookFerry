from __future__ import annotations

import argparse
import csv
import gzip
import os
import sys
from pathlib import Path

import requests


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import CATALOG_DB_NAME
from scripts.catalog_utils import (
    abort_catalog_rebuild,
    finish_catalog_rebuild,
    open_catalog_rebuild,
)


CATALOG_CODE = "gutenberg"
DEFAULT_CATALOG_URL = (
    "https://www.gutenberg.org/cache/epub/feeds/pg_catalog.csv.gz"
)
BATCH_SIZE = 5000


def download_catalog(url: str, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(f"{target.name}.part")

    print(f"Скачиваю Project Gutenberg: {url}")

    with requests.get(
        url,
        stream=True,
        timeout=(15, 180),
        headers={
            "User-Agent": (
                "BookFerry/1.0 "
                "(+https://github.com/TerentievKirill/BookFerry)"
            )
        },
    ) as response:
        response.raise_for_status()
        with temp.open("wb") as output:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    output.write(chunk)

    os.replace(temp, target)
    print(f"Каталог скачан: {target}")


def _required_columns(fieldnames: list[str] | None) -> dict[str, str]:
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


def import_books(conn, csv_gz: Path) -> int:
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
        columns = _required_columns(reader.fieldnames)

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


def build_catalog(csv_gz: Path, catalog_db: Path) -> None:
    conn, temp_db = open_catalog_rebuild(
        catalog_db=catalog_db,
        replace_catalog_code=CATALOG_CODE,
    )

    try:
        import_books(conn, csv_gz)
        conn.commit()
        finish_catalog_rebuild(conn, temp_db, catalog_db)
    except Exception:
        abort_catalog_rebuild(conn, temp_db)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Импорт Project Gutenberg в локальный каталог BookFerry"
    )
    parser.add_argument(
        "--catalog-db",
        default=CATALOG_DB_NAME,
        help="Путь к catalog.db",
    )
    parser.add_argument(
        "--source",
        default="/app/data/gutenberg/pg_catalog.csv.gz",
        help="Локальный путь к pg_catalog.csv.gz",
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_CATALOG_URL,
        help="URL официального CSV Project Gutenberg",
    )
    parser.add_argument(
        "--no-download",
        action="store_true",
        help="Не скачивать файл, использовать уже существующий --source",
    )
    args = parser.parse_args()

    source = Path(args.source)

    if not args.no_download:
        download_catalog(args.url, source)

    if not source.is_file():
        raise FileNotFoundError(f"Не найден файл: {source}")

    build_catalog(
        csv_gz=source,
        catalog_db=Path(args.catalog_db),
    )


if __name__ == "__main__":
    main()
