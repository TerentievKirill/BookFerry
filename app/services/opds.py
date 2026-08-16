from __future__ import annotations

import re
from urllib.parse import quote, urljoin

from lxml import etree

from app.models import Book
from app.services.safe_http import safe_get, validate_public_url


OPENSEARCH_TYPE = "application/opensearchdescription+xml"
# OpenSearch templates may use both {searchTerms} and optional {searchTerms?}.
SEARCH_TERMS_PATTERN = re.compile(r"\{searchTerms\??\}")


def _parse_xml(content: bytes, error_message: str):
    # OPDS XML comes from external servers, so parsing must not read
    # external files or make network requests.
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
    # OPDS 1.x catalogs are Atom feeds.
    # localname is used because different catalogs may use different XML namespace prefixes.
    return etree.QName(root).localname == "feed"


def _render_search_template(template: str, query: str) -> str:
    # OpenSearch uses placeholders inside the search URL.
    # Example:
    # /search?q={searchTerms}
    #
    # Some catalogs also declare optional parameters such as {count?}
    # or {startPage?}. We can safely remove optional parameters that
    # BookFerry does not use, but required unknown parameters are rejected.
    def replace(match: re.Match) -> str:
        raw_name = match.group(1)
        optional = raw_name.endswith("?")
        name = raw_name[:-1] if optional else raw_name

        if name == "searchTerms":
            return quote(query, safe="")

        if optional:
            return ""

        raise ValueError(
            f"OPDS requires unsupported search parameter: {{{raw_name}}}"
        )

    rendered = re.sub(r"\{([^{}]+)\}", replace, template)

    # No unresolved OpenSearch placeholders should remain after rendering.
    if "{" in rendered or "}" in rendered:
        raise ValueError("Invalid OPDS search template")
    # The generated URL is still external input and must pass SSRF validation.
    validate_public_url(rendered)
    return rendered


def _search_template_from_description(description_url: str) -> str:
    # Some OPDS catalogs do not put the search URL directly in rel="search".
    # Instead they link to an OpenSearch Description document which contains it.
    response = safe_get(description_url, timeout=(10, 30))
    try:
        response.raise_for_status()
        root = _parse_xml(
            response.content,
            "OpenSearch description contains invalid XML",
        )
        # OpenSearch descriptions may contain several <Url> entries
        # for different response formats. BookFerry needs the Atom one.
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
            # Templates may contain relative URLs.
            normalized = urljoin(description_url, template)

            # Render once with a harmless value to make sure the template
            # is usable before storing it in the user's settings.
            _render_search_template(normalized, "bookferry")
            return normalized

    raise ValueError(
        "OPDS catalog does not provide an Atom/OpenSearch search template"
    )


def inspect_opds(opds_url: str) -> tuple[str, str]:
    """Validate an OPDS catalog and return final URL plus search template."""
    response = safe_get(opds_url.strip(), timeout=(10, 30))

    try:
        response.raise_for_status()
        final_url = response.url
        root = _parse_xml(
            response.content,
            "The specified URL returned invalid XML",
        )
    finally:
        response.close()

    if not _is_feed(root):
        raise ValueError("The specified URL is not an OPDS/Atom feed")
    # XML namespaces differ between catalogs, so XPath uses local-name()
    # instead of hard-coded Atom namespace prefixes.
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
        # OPDS catalogs commonly advertise search in one of two ways:
        #
        # 1. rel="search" already contains an OpenSearch URL template.
        # 2. rel="search" points to a separate OpenSearch Description document.
        if SEARCH_TERMS_PATTERN.search(target):
            _render_search_template(target, "bookferry")
            return final_url, target

        if OPENSEARCH_TYPE in media_type:
            return final_url, _search_template_from_description(target)

    raise ValueError(
        "OPDS catalog was found, but it does not provide search via rel=search"
    )


def _parse_books(root, response_url: str) -> list[Book]:
    # OPDS search results are Atom <entry> elements.
    # local-name() keeps parsing independent from namespace prefixes.
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
        # A result may contain links to PDF, TXT and other formats.
        # BookFerry currently accepts EPUB acquisition links only.
        epub_links = entry.xpath(
            './*[local-name()="link"]'
            '[contains(translate(@type, '
            '"ABCDEFGHIJKLMNOPQRSTUVWXYZ", '
            '"abcdefghijklmnopqrstuvwxyz"), '
            '"application/epub+zip")]/@href'
        )
        # Entries without a title or supported download link are useless
        # to the client and are simply skipped.
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
        # For the next page OPDS gives us a ready-made URL,
        # so the original search template is no longer needed.
        request_url = page_url
        validate_public_url(request_url)
    else:
        if not search_template:
            raise ValueError("Search is not configured for this custom OPDS")
        request_url = _render_search_template(search_template, query)

    response = safe_get(request_url, timeout=(10, 180))

    try:
        response.raise_for_status()
        root = _parse_xml(
            response.content,
            "OPDS returned invalid XML during search",
        )
        response_url = response.url
    finally:
        response.close()

    if not _is_feed(root):
        raise ValueError("OPDS search returned something other than an Atom feed")
    # OPDS pagination is different from local search pagination:
    # the catalog itself provides the URL of the next Atom page.
    next_links = root.xpath(
        '/*[local-name()="feed"]'
        '/*[local-name()="link"]'
        '[@rel="next"]/@href'
    )

    next_page_url = None
    if next_links:
        next_page_url = urljoin(response_url, next_links[0])
        # Never trust a pagination URL returned by an external catalog.
        validate_public_url(next_page_url)

    return _parse_books(root, response_url), next_page_url
