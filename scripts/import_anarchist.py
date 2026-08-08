from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urljoin, urlparse

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


CATALOG_CODE = "anarchist"
DEFAULT_OPDS_URL = "https://theanarchistlibrary.org/opds/titles/1"
BATCH_SIZE = 1000
MAX_PAGES = 10000


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


def _epub_link(entry: ET.Element, page_url: str) -> str | None:
    for child in entry:
        if _local_name(child.tag) != "link":
            continue

        href = (child.attrib.get("href") or "").strip()
        link_type = (child.attrib.get("type") or "").lower()

        if not href:
            continue

        if "epub" in link_type or href.lower().endswith(".epub"):
            return urljoin(page_url, href)

    return None


def _slug_from_epub_url(epub_url: str) -> str | None:
    path = urlparse(epub_url).path

    if not path.startswith("/library/") or not path.endswith(".epub"):
        return None

    slug = path[len("/library/"):-len(".epub")].strip("/")

    if not slug or "/" in slug:
        return None

    return slug


def _next_page(root: ET.Element, page_url: str) -> str | None:
    for child in root:
        if _local_name(child.tag) != "link":
            continue

        rel = (child.attrib.get("rel") or "").lower()
        href = (child.attrib.get("href") or "").strip()

        if rel == "next" and href:
            return urljoin(page_url, href)

    return None


def fetch_page(session: requests.Session, url: str) -> tuple[ET.Element, str]:
    response = session.get(
        url,
        timeout=(15, 180),
        headers={
            "User-Agent": (
                "BookFerry/1.0 "
                "(+https://github.com/TerentievKirill/BookFerry)"
            )
        },
    )
    response.raise_for_status()

    try:
        root = ET.fromstring(response.content)
    except ET.ParseError as error:
        raise ValueError(
            f"The Anarchist Library вернул невалидный OPDS: {response.url}"
        ) from error

    if _local_name(root.tag) != "feed":
        raise ValueError(
            f"The Anarchist Library вернул не OPDS feed: {response.url}"
        )

    return root, response.url


def import_books(conn, opds_url: str) -> int:
    sql = """
        INSERT OR IGNORE INTO books (
            catalog_code,
            external_id,
            title,
            author,
            language
        )
        VALUES ('anarchist', ?, ?, ?, ?)
    """

    session = requests.Session()
    visited: set[str] = set()
    batch: list[tuple[str, str, str, str]] = []
    imported = 0
    page_number = 0
    next_url: str | None = opds_url

    while next_url:
        if next_url in visited:
            raise ValueError(f"Зацикленная OPDS-пагинация: {next_url}")

        if page_number >= MAX_PAGES:
            raise ValueError("Слишком много страниц OPDS")

        visited.add(next_url)
        page_number += 1

        root, current_url = fetch_page(session, next_url)

        for entry in root:
            if _local_name(entry.tag) != "entry":
                continue

            title = _child_text(entry, "title")
            if not title:
                continue

            epub_url = _epub_link(entry, current_url)
            if not epub_url:
                continue

            slug = _slug_from_epub_url(epub_url)
            if not slug:
                continue

            author = _authors(entry)
            language = _child_text(entry, "language") or "en"

            batch.append((slug, title, author, language))
            imported += 1

            if len(batch) >= BATCH_SIZE:
                conn.executemany(sql, batch)
                batch.clear()

        if page_number % 10 == 0:
            print(
                f"The Anarchist Library: страниц {page_number}, "
                f"текстов {imported:,}"
            )

        next_url = _next_page(root, current_url)

    if batch:
        conn.executemany(sql, batch)

    print(
        f"The Anarchist Library: {imported:,} текстов, "
        f"страниц OPDS: {page_number}"
    )
    return imported


def build_catalog(opds_url: str, catalog_db: Path) -> None:
    conn, temp_db = open_catalog_rebuild(
        catalog_db=catalog_db,
        replace_catalog_code=CATALOG_CODE,
    )

    try:
        imported = import_books(conn, opds_url)
        if imported == 0:
            raise ValueError("OPDS The Anarchist Library не содержит EPUB-текстов")
        conn.commit()
        finish_catalog_rebuild(conn, temp_db, catalog_db)
    except Exception:
        abort_catalog_rebuild(conn, temp_db)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Импорт The Anarchist Library в локальный каталог BookFerry"
        )
    )
    parser.add_argument(
        "--catalog-db",
        default=CATALOG_DB_NAME,
        help="Путь к catalog.db",
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_OPDS_URL,
        help="Первая страница списка текстов OPDS The Anarchist Library",
    )
    args = parser.parse_args()

    build_catalog(
        opds_url=args.url,
        catalog_db=Path(args.catalog_db),
    )


if __name__ == "__main__":
    main()
