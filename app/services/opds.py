import requests
from lxml import etree
from urllib.parse import urljoin

from app.models import Book


MAX_BOOKS = 60


def search_opds(
    url: str,
    query: str,
) -> list[Book]:
    books: list[Book] = []

    next_url: str | None = f"{url.rstrip('/')}/search"
    params: dict | None = {
        "searchType": "books",
        "searchTerm": query,
    }

    visited_urls: set[str] = set()

    while next_url and len(books) < MAX_BOOKS:
        # Защита от ситуации, если OPDS начнёт возвращать
        # одну и ту же ссылку rel="next".
        if next_url in visited_urls:
            break

        visited_urls.add(next_url)

        try:
            response = requests.get(
                next_url,
                params=params,
                timeout=15,
            )
            response.raise_for_status()

        except requests.RequestException:
            # Если уже что-то нашли — возвращаем частичный результат.
            if books:
                break

            # Если сломалась первая же страница — отдаём ошибку наверх.
            raise

        root = etree.fromstring(response.content)

        entries = root.xpath(
            '//*[local-name()="entry"]'
        )

        if not entries:
            break

        for entry in entries:
            title_values = entry.xpath(
                './*[local-name()="title"]/text()'
            )

            author_values = entry.xpath(
                './*[local-name()="author"]'
                '/*[local-name()="name"]/text()'
            )

            epub_links = entry.xpath(
                './*[local-name()="link"]'
                '[@type="application/epub+zip"]/@href'
            )

            if not title_values or not epub_links:
                continue

            books.append(
                Book(
                    author=(
                        author_values[0].strip()
                        if author_values
                        else ""
                    ),
                    title=title_values[0].strip(),
                    url=urljoin(url, epub_links[0]),
                )
            )

            if len(books) >= MAX_BOOKS:
                break

        next_links = root.xpath(
            '//*[local-name()="link"]'
            '[@rel="next"]/@href'
        )

        if not next_links:
            break

        next_url = urljoin(url, next_links[0])

        # В ссылке rel="next" параметры уже указаны самой Flibusta.
        params = None

    return books
