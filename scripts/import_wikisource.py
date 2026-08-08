from __future__ import annotations

import argparse
import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import parse_qs, urlparse

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


CATALOG_CODE = "wikisource"
DEFAULT_OPDS_URL = (
    "https://ws-export.wmcloud.org/opds/ru/Ready_for_export.xml"
)
BATCH_SIZE = 1000


def download_catalog(url: str, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(f"{target.name}.part")

    print(f"Скачиваю OPDS Викитеки: {url}")

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
    print(f"OPDS скачан: {target}")


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child_text(element: ET.Element, name: str) -> str:
    for child in element:
        if _local_name(child.tag) == name:
            return (child.text or "").strip()
    return ""


def _authors(entry: ET.Element) -> str:
    names: list[str] = []

    for child in entry:
        if _local_name(child.tag) != "author":
            continue
        name = _child_text(child, "name")
        if name:
            names.append(name)

    return ", ".join(names)


def _epub_link(entry: ET.Element) -> str | None:
    candidates: list[str] = []

    for child in entry:
        if _local_name(child.tag) != "link":
            continue

        href = (child.attrib.get("href") or "").strip()
        link_type = (child.attrib.get("type") or "").lower()
        rel = (child.attrib.get("rel") or "").lower()

        if not href:
            continue

        if "epub" in link_type:
            return href

        if "acquisition" in rel and "epub" in href.lower():
            candidates.append(href)

    return candidates[0] if candidates else None


def _page_name(epub_url: str, title: str) -> str:
    query = parse_qs(urlparse(epub_url).query)
    page = query.get("page", [""])[0].strip()
    return page or title


def import_books(conn, opds_file: Path) -> int:
    root = ET.parse(opds_file).getroot()

    if _local_name(root.tag) != "feed":
        raise ValueError(
            "Вместо OPDS Викитеки получен другой документ. "
            "Возможно, WS Export временно блокирует запрос."
        )

    sql = """
        INSERT OR IGNORE INTO books (
            catalog_code,
            external_id,
            title,
            author,
            language
        )
        VALUES ('wikisource', ?, ?, ?, 'ru')
    """

    batch: list[tuple[str, str, str]] = []
    imported = 0

    for entry in root.iter():
        if _local_name(entry.tag) != "entry":
            continue

        title = _child_text(entry, "title")
        epub_url = _epub_link(entry)

        if not title or not epub_url:
            continue

        page_name = _page_name(epub_url, title)
        author = _authors(entry)

        batch.append((page_name, title, author))
        imported += 1

        if len(batch) >= BATCH_SIZE:
            conn.executemany(sql, batch)
            batch.clear()

    if batch:
        conn.executemany(sql, batch)

    print(f"Викитека: {imported:,} книг")
    return imported


def build_catalog(opds_file: Path, catalog_db: Path) -> None:
    conn, temp_db = open_catalog_rebuild(
        catalog_db=catalog_db,
        replace_catalog_code=CATALOG_CODE,
    )

    try:
        imported = import_books(conn, opds_file)
        if imported == 0:
            raise ValueError("OPDS Викитеки не содержит EPUB-книг")
        conn.commit()
        finish_catalog_rebuild(conn, temp_db, catalog_db)
    except Exception:
        abort_catalog_rebuild(conn, temp_db)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Импорт русской Викитеки в локальный каталог BookFerry"
    )
    parser.add_argument(
        "--catalog-db",
        default=CATALOG_DB_NAME,
        help="Путь к catalog.db",
    )
    parser.add_argument(
        "--source",
        default="/app/data/wikisource/ready_for_export.xml",
        help="Локальный путь к OPDS XML",
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_OPDS_URL,
        help="URL OPDS русской Викитеки",
    )
    parser.add_argument(
        "--no-download",
        action="store_true",
        help="Не скачивать OPDS, использовать уже существующий --source",
    )
    args = parser.parse_args()

    source = Path(args.source)

    if not args.no_download:
        download_catalog(args.url, source)

    if not source.is_file():
        raise FileNotFoundError(f"Не найден файл: {source}")

    build_catalog(
        opds_file=source,
        catalog_db=Path(args.catalog_db),
    )


if __name__ == "__main__":
    main()
