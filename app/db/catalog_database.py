import sqlite3
from contextlib import contextmanager

from app.config import CATALOG_DB_NAME


@contextmanager
def get_catalog_connection():
    conn = sqlite3.connect(CATALOG_DB_NAME)
    conn.row_factory = sqlite3.Row

    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def create_catalog_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS books (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            catalog_code TEXT NOT NULL,
            external_id TEXT NOT NULL,
            title TEXT NOT NULL,
            author TEXT,
            language TEXT,

            UNIQUE(catalog_code, external_id)
        )
        """
    )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_books_catalog_code
        ON books (catalog_code)
        """
    )

    conn.execute(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS books_fts
        USING fts5(
            title,
            author,
            content='books',
            content_rowid='id'
        )
        """
    )


def init_catalog_db() -> None:
    with get_catalog_connection() as conn:
        create_catalog_schema(conn)


def rebuild_search_index() -> None:
    with get_catalog_connection() as conn:
        conn.execute(
            """
            INSERT INTO books_fts(books_fts)
            VALUES ('rebuild')
            """
        )
