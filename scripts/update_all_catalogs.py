from __future__ import annotations

import fcntl
import os
import sqlite3
import sys
import time
from pathlib import Path

import requests


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import CATALOG_DB_NAME
from app.db.catalog_database import create_catalog_schema
from scripts.catalog_utils import abort_catalog_rebuild, finish_catalog_rebuild
from scripts.import_anarchist import import_books as import_amusewiki_books
from scripts.import_flibusta import (
    fill_book_authors,
    import_author_links,
    import_authors,
    import_books as import_flibusta_books,
)
from scripts.import_gutenberg import (
    DEFAULT_CATALOG_URL as GUTENBERG_CATALOG_URL,
    download_catalog as download_gutenberg_catalog,
    import_books as import_gutenberg_books,
)


DATA_DIR = Path("/app/data")
FLIBUSTA_DIR = DATA_DIR / "flibusta_sql"
GUTENBERG_SOURCE = DATA_DIR / "gutenberg" / "pg_catalog.csv.gz"
LOCK_FILE = DATA_DIR / "catalog-update.lock"

FLIBUSTA_DUMPS = {
    "lib.libbook.sql.gz": "https://flibusta.is/sql/lib.libbook.sql.gz",
    "lib.libavtor.sql.gz": "https://flibusta.is/sql/lib.libavtor.sql.gz",
    "lib.libavtorname.sql.gz": "https://flibusta.is/sql/lib.libavtorname.sql.gz",
}

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


def download_flibusta_dumps() -> None:
    print("\n=== FLIBUSTA: скачивание дампов ===")
    for filename, url in FLIBUSTA_DUMPS.items():
        _download_file(url, FLIBUSTA_DIR / filename)


def _new_catalog_connection(catalog_db: Path) -> tuple[sqlite3.Connection, Path]:
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


def import_flibusta(conn: sqlite3.Connection) -> None:
    print("\n=== FLIBUSTA: импорт ===")
    import_authors(conn, FLIBUSTA_DIR / "lib.libavtorname.sql.gz")
    conn.commit()

    import_author_links(conn, FLIBUSTA_DIR / "lib.libavtor.sql.gz")
    conn.commit()

    import_flibusta_books(conn, FLIBUSTA_DIR / "lib.libbook.sql.gz")
    conn.commit()

    fill_book_authors(conn)
    conn.commit()
    _validate_catalog(conn, "flibusta")


def import_gutenberg(conn: sqlite3.Connection) -> None:
    print("\n=== PROJECT GUTENBERG ===")
    download_gutenberg_catalog(GUTENBERG_CATALOG_URL, GUTENBERG_SOURCE)
    import_gutenberg_books(conn, GUTENBERG_SOURCE)
    conn.commit()
    _validate_catalog(conn, "gutenberg")


def import_anarchist_en(conn: sqlite3.Connection) -> None:
    print("\n=== THE ANARCHIST LIBRARY ===")
    import_amusewiki_books(
        conn=conn,
        opds_url=ANARCHIST_EN_URL,
        catalog_code="anarchist",
        catalog_name="The Anarchist Library",
        default_language="en",
    )
    conn.commit()
    _validate_catalog(conn, "anarchist")


def import_anarchist_ru(conn: sqlite3.Connection) -> None:
    print("\n=== БИБЛИОТЕКА АНАРХИЗМА ===")
    import_amusewiki_books(
        conn=conn,
        opds_url=ANARCHIST_RU_URL,
        catalog_code="anarchist_ru",
        catalog_name="Библиотека Анархизма",
        default_language="ru",
    )
    conn.commit()
    _validate_catalog(conn, "anarchist_ru")


def update_all_catalogs(catalog_db: Path) -> None:
    started = time.monotonic()

    download_flibusta_dumps()

    conn, temp_db = _new_catalog_connection(catalog_db)

    try:
        import_flibusta(conn)
        import_gutenberg(conn)
        import_anarchist_en(conn)
        import_anarchist_ru(conn)

        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise ValueError(f"SQLite integrity_check: {integrity}")

        total = conn.execute("SELECT COUNT(*) FROM books").fetchone()[0]
        print(f"\nВсего записей перед установкой: {total:,}")

        finish_catalog_rebuild(conn, temp_db, catalog_db)

    except Exception:
        abort_catalog_rebuild(conn, temp_db)
        raise

    elapsed = time.monotonic() - started
    print(f"Полное обновление завершено за {elapsed / 60:.1f} мин.")


def main() -> None:
    catalog_db = Path(CATALOG_DB_NAME)
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)

    with LOCK_FILE.open("w") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("Обновление каталогов уже выполняется. Новый запуск пропущен.")
            return

        lock.write(str(os.getpid()))
        lock.flush()
        update_all_catalogs(catalog_db)


if __name__ == "__main__":
    main()
