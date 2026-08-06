from urllib.parse import urljoin, urlparse

import requests
from lxml import etree

from app.models import Book


def _validate_page_url(
    opds_url: str,
    page_url: str,
) -> None:
    opds = urlparse(opds_url)
    page = urlparse(page_url)

    if (
        page.scheme not in {"http", "https"}
        or page.netloc != opds.netloc
    ):
        raise ValueError(
            "Некорректная ссылка следующей страницы"
        )


def search_opds(
    url: str,
    query: str,
    page_url: str | None = None,
) -> tuple[list[Book], str | None]:
    if page_url:
        _validate_page_url(url, page_url)
        request_url = page_url
        params = None
    else:
        request_url = f"{url.rstrip('/')}/search"
        params = {
            "searchType": "books",
            "searchTerm": query,
        }

    response = requests.get(
        request_url,
        params=params,
        timeout=180,
    )
    response.raise_for_status()

    root = etree.fromstring(response.content)

    next_links = root.xpath(
        '/*[local-name()="feed"]'
        '/*[local-name()="link"]'
        '[@rel="next"]/@href'
    )

    next_page_url = (
        urljoin(response.url, next_links[0])
        if next_links
        else None
    )

    books = []

    entries = root.xpath(
        '//*[local-name()="entry"]'
    )

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
                    author_values[0]
                    if author_values
                    else ""
                ),
                title=title_values[0],
                url=urljoin(
                    response.url,
                    epub_links[0],
                ),
            )
        )

    return books, next_page_url
