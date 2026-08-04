import requests
from lxml import etree
from urllib.parse import urljoin

from app.models import Book


def search_opds(
    url: str,
    query: str,
) -> list[Book]:
    books = []

    search_url = f"{url.rstrip('/')}/search"

    for page_number in range(10):
        response = requests.get(
            search_url,
            params={
                "searchType": "books",
                "searchTerm": query,
                "pageNumber": page_number,
            },
            timeout=15,
        )
        response.raise_for_status()

        root = etree.fromstring(response.content)

        entries = root.xpath(
            '//*[local-name()="entry"]'
        )

        if not entries:
            break

        for entry in entries:
            title = entry.xpath(
                './*[local-name()="title"]/text()'
            )[0]

            author = entry.xpath(
                './*[local-name()="author"]'
                '/*[local-name()="name"]/text()'
            )[0]

            epub_link = entry.xpath(
                './*[local-name()="link"]'
                '[@type="application/epub+zip"]/@href'
            )

            if not epub_link:
                continue

            books.append(
                Book(
                    author=author,
                    title=title,
                    url=urljoin(url, epub_link[0]),
                )
            )

    return books