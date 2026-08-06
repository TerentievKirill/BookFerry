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
        try:
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

        except requests.RequestException:
            # Если предыдущие страницы уже загрузились,
            # возвращаем найденные книги.
            if books:
                break

            # Если не загрузилась даже первая страница,
            # передаём ошибку обработчику API.
            raise

        root = etree.fromstring(response.content)

        entries = root.xpath(
            '//*[local-name()="entry"]'
        )

        # Следующих страниц с книгами уже нет.
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
                    author=author_values[0] if author_values else "",
                    title=title_values[0],
                    url=urljoin(url, epub_links[0]),
                )
            )

    return books