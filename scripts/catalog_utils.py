from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from app.db.catalog_database import create_catalog_schema


def open_catalog_rebuild(
    catalog_db: Path,
    replace_catalog_code: str,
) -> tuple[sqlite3.Connection, Path]:
    """Create a new catalog DB while preserving every other catalog."""
    catalog_db.parent.mkdir(parents=True, exist_ok=True)
    temp_db = catalog_db.with_name(f"{catalog_db.name}.new")

    if temp_db.exists():
        temp_db.unlink()

    conn = sqlite3.connect(temp_db)
    conn.execute("PRAGMA journal_mode = OFF")
    conn.execute("PRAGMA synchronous = OFF")
    conn.execute("PRAGMA temp_store = FILE")
    create_catalog_schema(conn)

    if catalog_db.is_file() and catalog_db.stat().st_size > 0:
        conn.execute(
            "ATTACH DATABASE ? AS current_catalog",
            (str(catalog_db),),
        )
        try:
            conn.execute(
                """
                INSERT INTO books (
                    catalog_code,
                    external_id,
                    title,
                    author,
                    language
                )
                SELECT
                    catalog_code,
                    external_id,
                    title,
                    author,
                    language
                FROM current_catalog.books
                WHERE catalog_code <> ?
                """,
                (replace_catalog_code,),
            )
            conn.commit()
        finally:
            conn.execute("DETACH DATABASE current_catalog")

    return conn, temp_db


def finish_catalog_rebuild(
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


def abort_catalog_rebuild(
    conn: sqlite3.Connection,
    temp_db: Path,
) -> None:
    conn.close()
    if temp_db.exists():
        temp_db.unlink()
