import sqlite3
import uuid

from app.db.database import get_connection


SUPPORTED_CLIENT_TYPES = {"telegram", "pocketbook", "flutter"}


def _default_catalog_id(cursor):
    row = cursor.execute(
        """
        SELECT id FROM catalogs
        WHERE enabled = 1
        ORDER BY sort_order, id
        LIMIT 1
        """
    ).fetchone()
    if row is None:
        raise ValueError("No enabled catalogs")
    return row[0]


def register_user(client_type: str, external_id: str | None = None):
    if client_type not in SUPPORTED_CLIENT_TYPES:
        raise ValueError("Unsupported client type")
    if client_type == "telegram" and external_id is None:
        raise ValueError("external_id is required for Telegram")

    with get_connection() as conn:
        cursor = conn.cursor()
        uid = str(uuid.uuid4())
        cursor.execute(
            """
            INSERT INTO users (
                uid,
                client_type,
                external_id,
                catalog_id,
                last_seen_at
            )
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (uid, client_type, external_id, _default_catalog_id(cursor)),
        )
        return get_user_by_uid(uid, connection=conn)


def create_user(telegram_id: int):
    """Compatibility helper used by the Telegram client."""
    try:
        register_user("telegram", str(telegram_id))
        return True
    except sqlite3.IntegrityError:
        return False


def _select_user(where: str, value, connection=None):
    query = f"""
        SELECT users.id, users.uid, users.client_type, users.external_id,
               users.catalog_id,
               users.custom_opds_url,
               users.custom_opds_search_template,
               users.emails, users.subject, users.created_at,
               users.last_seen_at,
               COALESCE(users.custom_opds_url, catalogs.base_url) AS opds_url
        FROM users
        JOIN catalogs ON catalogs.id = users.catalog_id
        WHERE {where}
    """
    if connection is not None:
        return connection.execute(query, (value,)).fetchone()
    with get_connection() as conn:
        return conn.execute(query, (value,)).fetchone()


def get_user(telegram_id: int):
    return _select_user(
        "users.client_type = 'telegram' AND users.external_id = ?",
        str(telegram_id),
    )


def get_user_by_uid(uid: str, connection=None):
    return _select_user("users.uid = ?", uid, connection)


def touch_user(uid: str) -> bool:
    with get_connection() as conn:
        cursor = conn.execute(
            "UPDATE users SET last_seen_at = CURRENT_TIMESTAMP WHERE uid = ?",
            (uid,),
        )
        return cursor.rowcount > 0


def _update_user(field: str, value, where: str, identity):
    with get_connection() as conn:
        cursor = conn.execute(
            f"UPDATE users SET {field} = ? WHERE {where}",
            (value, identity),
        )
        return cursor.rowcount > 0


def update_email(telegram_id: int, emails: str):
    return _update_user(
        "emails", emails,
        "client_type = 'telegram' AND external_id = ?", str(telegram_id),
    )


def update_user_emails(uid: str, emails: str):
    return _update_user("emails", emails, "uid = ?", uid)


def update_subject(telegram_id: int, subject: str | None):
    return _update_user(
        "subject", subject,
        "client_type = 'telegram' AND external_id = ?", str(telegram_id),
    )


def update_user_subject(uid: str, subject: str | None):
    return _update_user("subject", subject, "uid = ?", uid)


def _update_catalog(where: str, identity, catalog_id: int) -> bool:
    with get_connection() as conn:
        cursor = conn.execute(
            f"""
            UPDATE users
            SET catalog_id = ?,
                custom_opds_url = NULL,
                custom_opds_search_template = NULL,
                last_seen_at = CURRENT_TIMESTAMP
            WHERE {where}
            """,
            (catalog_id, identity),
        )
        return cursor.rowcount > 0


def update_user_catalog(uid: str, catalog_id: int):
    return _update_catalog("uid = ?", uid, catalog_id)


def update_telegram_catalog(telegram_id: int, catalog_id: int):
    return _update_catalog(
        "client_type = 'telegram' AND external_id = ?",
        str(telegram_id),
        catalog_id,
    )


def _update_custom_opds(
    where: str,
    identity,
    opds_url: str,
    search_template: str,
) -> bool:
    with get_connection() as conn:
        cursor = conn.execute(
            f"""
            UPDATE users
            SET custom_opds_url = ?,
                custom_opds_search_template = ?,
                last_seen_at = CURRENT_TIMESTAMP
            WHERE {where}
            """,
            (opds_url, search_template, identity),
        )
        return cursor.rowcount > 0


def update_user_custom_opds(
    uid: str,
    opds_url: str,
    search_template: str,
) -> bool:
    return _update_custom_opds(
        "uid = ?",
        uid,
        opds_url,
        search_template,
    )


def update_telegram_custom_opds(
    telegram_id: int,
    opds_url: str,
    search_template: str,
) -> bool:
    return _update_custom_opds(
        "client_type = 'telegram' AND external_id = ?",
        str(telegram_id),
        opds_url,
        search_template,
    )


def delete_user(telegram_id: int):
    with get_connection() as conn:
        cursor = conn.execute(
            "DELETE FROM users WHERE client_type = 'telegram' AND external_id = ?",
            (str(telegram_id),),
        )
        return cursor.rowcount > 0
