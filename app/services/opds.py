import requests
from lxml import etree
from urllib.parse import urljoin

from app.models import Book


def search_opds(url: str, query: str) -> list[Book]:
    books = []

    response = requests.get(
        urljoin(url, "search"),
        params={
            "searchType": "books",
            "searchTerm": query,
        },
        timeout=15,
    )
    response.raise_for_status()

    root = etree.fromstring(response.content)

    entries = root.xpath(
        '//*[local-name()="entry"]'
    )

    for entry in entries:
        title_element = entry.xpath(
            './*[local-name()="title"]/text()'
        )

        author_element = entry.xpath(
            './*[local-name()="author"]'
            '/*[local-name()="name"]/text()'
        )

        epub_link = entry.xpath(
            './*[local-name()="link"]'
            '[@type="application/epub+zip"]/@href'
        )

        if not title_element or not epub_link:
            continue

        author = (
            author_element[0]
            if author_element
            else "Автор неизвестен"
        )

        books.append(
            Book(
                author=author,
                title=title_element[0],
                url=urljoin(url, epub_link[0]),
            )
        )

    return books