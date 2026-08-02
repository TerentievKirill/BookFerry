
import requests
from lxml import etree
from app.models import Book


def search_opds(url, query):
    books = []

    response = requests.get(
        f"{url}search",
        params={
            "searchType": "books",
            "searchTerm": query,
        },
    timeout = 15
    )
    response.raise_for_status()
    root = etree.fromstring(response.content)
    #  Ищем все теги <entry> в документе с помощью XPath
    entries = root.xpath('//*[local-name()="entry"]')
    for entry in entries:
        title_element = entry.xpath('./*[local-name()="title"]/text()')
        author_element = entry.xpath('./*[local-name()="author"]/*[local-name()="name"]/text()')

        title = title_element[0]
        author = author_element[0]

        epub_link = entry.xpath(
            './*[local-name()="link"][@type="application/epub+zip"]/@href'
        )

        if epub_link:
            download_url = "https://flibusta.is" + epub_link[0]
            books.append(
                Book(
                    author=author,
                    title=title,
                    url=download_url,
                )
            )
    return books

