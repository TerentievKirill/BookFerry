from __future__ import annotations

import re
from urllib.parse import quote, urljoin

from lxml import etree

from app.models import Book
from app.services.safe_http import safe_get, validate_public_url


OPENSEARCH_TYPE = "application/opensearchdescription+xml"
SEARCH_TERMS_PATTERN = re.compile(r"\{searchTerms\??\}")


def _parse_xml(content: bytes, error_message: str):
    parser = etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        recover=False,
    )

    try:
        return etree.fromstring(content, parser=parser)
    except etree.XMLSyntaxError as error:
        raise ValueError(error_message) from error


def _is_feed(root) -> bool:
    return etree.QName(root).localname == "feed"


def _render_search_template(template: str, query: str) -> str:
    def replace(match: re.Match) -> str:
        raw_name = match.group(1)
        optional = raw_name.endswith("?")
        name = raw_name[:-1] if optional else raw_name

        if name == "searchTerms":
            return quote(query, safe="")

        if optional:
            return ""

        raise ValueError(
            f"OPDS требует неподдерживаемый параметр поиска: {{{raw_name}}}"
        )

    rendered = re.sub(r"\{([^{}]+)\}", replace, template)

    if "{" in rendered or "}" in rendered:
        raise ValueError("Некорректный шаблон поиска OPDS")

    validate_public_url(rendered)
    return rendered


def _search_template_from_description(description_url: str) -> str:
    response = safe_get(description_url, timeout=(10, 30))
    try:
        response.raise_for_status()
        root = _parse_xml(
            response.content,
            "OpenSearch description содержит некорректный XML",
        )
    finally:
        response.close()

    candidates = root.xpath(
        '//*[local-name()="Url"][@template]'
    )

    for item in candidates:
        media_type = (item.get("type") or "").lower()
        template = (item.get("template") or "").strip()

        if (
            "application/atom+xml" in media_type
            and SEARCH_TERMS_PATTERN.search(template)
        ):
            normalized = urljoin(description_url, template)
            _render_search_template(normalized, "bookferry")
            return normalized

    raise ValueError(
        "OPDS-каталог не объявляет поисковый Atom/OpenSearch шаблон"
    )


def inspect_opds(opds_url: str) -> tuple[str, str]:
    """Validate an OPDS catalog and return final URL plus search template."""
    response = safe_get(opds_url.strip(), timeout=(10, 30))

    try:
        response.raise_for_status()
        final_url = response.url
        root = _parse_xml(
            response.content,
            "По указанному адресу получен невалидный XML",
        )
    finally:
        response.close()

    if not _is_feed(root):
        raise ValueError("По указанному адресу найден не OPDS/Atom feed")

    search_links = root.xpath(
        '/*[local-name()="feed"]'
        '/*[local-name()="link"]'
        '[@rel="search"]'
    )

    for link in search_links:
        href = (link.get("href") or "").strip()
        media_type = (link.get("type") or "").lower()

        if not href:
            continue

        target = urljoin(final_url, href)

        if SEARCH_TERMS_PATTERN.search(target):
            _render_search_template(target, "bookferry")
            return final_url, target

        if OPENSEARCH_TYPE in media_type:
            return final_url, _search_template_from_description(target)

    raise ValueError(
        "OPDS-каталог найден, но он не объявляет поиск через rel=search"
    )


def _parse_books(root, response_url: str) -> list[Book]:
    books: list[Book] = []

    entries = root.xpath('//*[local-name()="entry"]')

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
            '[contains(translate(@type, '
            '"ABCDEFGHIJKLMNOPQRSTUVWXYZ", '
            '"abcdefghijklmnopqrstuvwxyz"), '
            '"application/epub+zip")]/@href'
        )

        if not title_values or not epub_links:
            continue

        books.append(
            Book(
                author=", ".join(
                    value.strip()
                    for value in author_values
                    if value.strip()
                ),
                title=title_values[0].strip(),
                url=urljoin(response_url, epub_links[0]),
            )
        )

    return books


def search_opds(
    url: str,
    query: str,
    page_url: str | None = None,
    search_template: str | None = None,
) -> tuple[list[Book], str | None]:
    if page_url:
        request_url = page_url
        validate_public_url(request_url)
    else:
        if not search_template:
            raise ValueError("Для пользовательского OPDS не настроен поиск")
        request_url = _render_search_template(search_template, query)

    response = safe_get(request_url, timeout=(10, 180))

    try:
        response.raise_for_status()
        root = _parse_xml(
            response.content,
            "OPDS вернул некорректный XML при поиске",
        )
        response_url = response.url
    finally:
        response.close()

    if not _is_feed(root):
        raise ValueError("OPDS вернул не Atom feed при поиске")

    next_links = root.xpath(
        '/*[local-name()="feed"]'
        '/*[local-name()="link"]'
        '[@rel="next"]/@href'
    )

    next_page_url = None
    if next_links:
        next_page_url = urljoin(response_url, next_links[0])
        validate_public_url(next_page_url)

    return _parse_books(root, response_url), next_page_url
