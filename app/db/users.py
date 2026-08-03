from app.db.database import get_connection


from app.config import DEFAULT_OPDS_URL


def create_user(telegram_id: int):
    with get_connection() as conn:
        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT OR IGNORE INTO users (telegram_id, opds_url)
            VALUES (?, ?)
            """,
            (telegram_id, DEFAULT_OPDS_URL),
        )
        return cursor.rowcount > 0



def get_user(telegram_id: int):
    with get_connection() as conn:
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT id, telegram_id, emails, subject, opds_url
            FROM users
            WHERE telegram_id = ?
            """,
            (telegram_id,),
        )

        return cursor.fetchone()

def update_email(
    telegram_id: int,
    emails: str,
):
    with get_connection() as conn:
        cursor = conn.cursor()

        cursor.execute(
            """
            UPDATE users
            SET emails = ?
            WHERE telegram_id = ?
            """,
            (emails, telegram_id),
        )

    return cursor.rowcount > 0

def update_subject(
    telegram_id: int,
    subject: str | None,
):
    with get_connection() as conn:
        cursor = conn.cursor()

        cursor.execute(
            """
            UPDATE users
            SET subject = ?
            WHERE telegram_id = ?
            """,
            (subject, telegram_id),
        )

        return cursor.rowcount > 0
def update_opds(
    telegram_id: int,
    opds_url: str,
):
    with get_connection() as conn:
        cursor = conn.cursor()

        cursor.execute(
            """
            UPDATE users
            SET opds_url = ?
            WHERE telegram_id = ?
            """,
            (opds_url, telegram_id),
        )

    return cursor.rowcount > 0



def delete_user(telegram_id: int):
    with get_connection() as conn:
        cursor = conn.cursor()

        cursor.execute(
            """
            DELETE FROM users
            WHERE telegram_id = ?
            """,
            (telegram_id,),
        )

        return cursor.rowcount > 0