from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path


COLUMNS = {
    "custom_opds_url": "TEXT",
    "custom_opds_search_template": "TEXT",
}


def migrate(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)

    try:
        existing = {
            row[1]
            for row in conn.execute("PRAGMA table_info(users)")
        }

        for name, column_type in COLUMNS.items():
            if name in existing:
                print(f"{name}: уже есть")
                continue

            conn.execute(
                f"ALTER TABLE users ADD COLUMN {name} {column_type}"
            )
            print(f"{name}: добавлена")

        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "db_path",
        nargs="?",
        default="/opt/data/bookferry.db",
    )
    args = parser.parse_args()
    migrate(Path(args.db_path))
