from __future__ import annotations

import argparse
import sys
from urllib.parse import unquote

import requests


def _fields(response: requests.Response) -> list[str]:
    response.raise_for_status()
    return response.text.strip().split("\t")


def _register(session: requests.Session, base_url: str) -> tuple[str, str]:
    response = session.get(
        f"{base_url}/pocketbook/register",
        timeout=30,
    )
    fields = _fields(response)
    if len(fields) < 4 or fields[0] != "UID":
        raise RuntimeError(f"Unexpected register response: {response.text!r}")
    return fields[1], unquote(fields[3])


def _catalogs(session: requests.Session, base_url: str) -> list[tuple[int, str]]:
    response = session.get(
        f"{base_url}/pocketbook/catalogs",
        timeout=30,
    )
    response.raise_for_status()

    result = []
    for line in response.text.splitlines():
        fields = line.split("\t")
        if len(fields) >= 3 and fields[0] == "CATALOG":
            result.append((int(fields[1]), unquote(fields[2])))
    return result


def _select_catalog(
    session: requests.Session,
    base_url: str,
    uid: str,
    catalog_id: int,
) -> str:
    response = session.get(
        f"{base_url}/pocketbook/{uid}/catalog/{catalog_id}",
        timeout=30,
    )
    fields = _fields(response)
    if len(fields) < 3 or fields[0] != "OK":
        raise RuntimeError(f"Unexpected catalog response: {response.text!r}")
    return unquote(fields[2])


def _search(
    session: requests.Session,
    base_url: str,
    uid: str,
    query: str,
) -> list[tuple[str, str, str]]:
    response = session.get(
        f"{base_url}/pocketbook/{uid}/search",
        params={"q": query},
        timeout=60,
    )
    response.raise_for_status()

    books = []
    for line in response.text.splitlines():
        fields = line.split("\t")
        if len(fields) >= 4 and fields[0] == "BOOK":
            books.append(
                (
                    unquote(fields[1]),
                    unquote(fields[2]),
                    fields[3],
                )
            )
    return books


def _download_first(
    session: requests.Session,
    base_url: str,
    uid: str,
    token: str,
) -> tuple[int, str | None]:
    response = session.get(
        f"{base_url}/pocketbook/{uid}/download/{token}",
        timeout=120,
    )
    response.raise_for_status()

    if len(response.content) < 4 or not response.content.startswith(b"PK"):
        raise RuntimeError(
            "Downloaded file does not look like EPUB/ZIP: "
            f"status={response.status_code}, bytes={len(response.content)}"
        )

    return len(response.content), response.headers.get("content-disposition")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--base-url",
        default="https://api.heartlab.app",
    )
    parser.add_argument(
        "--query",
        default="лабиринт отражений",
    )
    parser.add_argument(
        "--catalog",
        default="Flibusta",
    )
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")

    with requests.Session() as session:
        uid, default_catalog = _register(session, base_url)
        print(f"REGISTER: uid={uid}, default={default_catalog}")

        catalogs = _catalogs(session, base_url)
        print("CATALOGS:")
        for catalog_id, name in catalogs:
            print(f"  {catalog_id}: {name}")

        target = next(
            (
                (catalog_id, name)
                for catalog_id, name in catalogs
                if name.casefold() == args.catalog.casefold()
            ),
            None,
        )
        if target is None:
            raise RuntimeError(f"Catalog not found: {args.catalog}")

        selected = _select_catalog(
            session,
            base_url,
            uid,
            target[0],
        )
        print(f"SELECT: {selected}")

        books = _search(
            session,
            base_url,
            uid,
            args.query,
        )
        print(f"SEARCH: query={args.query!r}, found={len(books)}")
        for title, author, _ in books[:5]:
            print(f"  {title} — {author}")

        if not books:
            raise RuntimeError("Search returned no books")

        size, disposition = _download_first(
            session,
            base_url,
            uid,
            books[0][2],
        )
        print(
            "DOWNLOAD: "
            f"bytes={size}, content_disposition={disposition!r}, ZIP=OK"
        )

    print("POCKETBOOK SMOKE: PASSED")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"POCKETBOOK SMOKE: FAILED: {error}", file=sys.stderr)
        raise
