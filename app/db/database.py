import sqlite3
from contextlib import contextmanager

from app.config import DB_NAME, DEFAULT_OPDS_URL


CATALOGS = (
    ("gutenberg", "Project Gutenberg", "https://www.gutenberg.org/ebooks.opds/", 1),
    ("anarchist", "The Anarchist Library", "https://theanarchistlibrary.org/", 2),
    ("flibusta", "Flibusta", DEFAULT_OPDS_URL or "https://flibusta.is/opds/", 3),
    ("anarchist_ru", "Библиотека Анархизма", "https://ru.anarchistlibraries.net/", 4),
)


@contextmanager
def get_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _create_catalogs(cursor):
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS catalogs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            base_url TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            sort_order INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    cursor.executemany(
        """
        INSERT INTO catalogs (code, name, base_url, sort_order)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(code) DO UPDATE SET
            name = excluded.name,
            base_url = excluded.base_url,
            sort_order = excluded.sort_order
        """,
        CATALOGS,
    )


def _create_users(cursor):
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            uid TEXT UNIQUE NOT NULL,
            client_type TEXT NOT NULL,
            external_id TEXT,
            catalog_id INTEGER NOT NULL,
            custom_opds_url TEXT,
            custom_opds_search_template TEXT,
            emails TEXT,
            subject TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (catalog_id) REFERENCES catalogs(id)
        )
        """
    )
    cursor.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS users_client_external_id_unique
        ON users (client_type, external_id)
        WHERE external_id IS NOT NULL
        """
    )


def init_db():
    with get_connection() as conn:
        cursor = conn.cursor()
        _create_catalogs(cursor)
        _create_users(cursor)
