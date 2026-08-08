from app.db.database import get_connection


def get_catalogs():
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT id, code, name, base_url, enabled, sort_order
            FROM catalogs
            WHERE enabled = 1
            ORDER BY sort_order, id
            """
        ).fetchall()


def get_catalog(catalog_id: int):
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT id, code, name, base_url, enabled, sort_order
            FROM catalogs WHERE id = ?
            """,
            (catalog_id,),
        ).fetchone()


def get_catalog_by_code(code: str):
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT id, code, name, base_url, enabled, sort_order
            FROM catalogs WHERE code = ?
            """,
            (code,),
        ).fetchone()
