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


def init_catalog_db():
    with get_catalog_connection() as conn:
        cursor = conn.cursor()

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS books (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                catalog_code TEXT NOT NULL,
                external_id TEXT NOT NULL,
                title TEXT NOT NULL,
                author TEXT,
                language TEXT,
                download_url TEXT,

                UNIQUE(catalog_code, external_id)
            )
            """
        )

        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_books_catalog_code
            ON books (catalog_code)
            """
        )

        cursor.execute(
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


def rebuild_search_index():
    with get_catalog_connection() as conn:
        conn.execute(
            """
            INSERT INTO books_fts(books_fts)
            VALUES ('rebuild')
            """
        )