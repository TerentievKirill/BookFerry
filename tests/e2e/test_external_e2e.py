import pytest

from tests.framework.models import SearchResponse


CATALOG_CASES = [
    pytest.param(
        1,
        "alice adams",
        "Alice Adams",
        id="gutenberg",
    ),
    pytest.param(
        2,
        "anarchism other essays",
        "Anarchism and Other Essays",
        id="anarchist",
    ),
    pytest.param(
        3,
        "лабиринт отражений",
        "Лабиринт отражений",
        id="flibusta",
    ),
    pytest.param(
        4,
        "государственность анархия",
        "Государственность и анархия",
        id="anarchist-ru",
    ),
]


def _find_expected_book(api, uid, query, expected_title):
    response = api.search(uid=uid, query=query)

    assert response.status_code == 200

    result = SearchResponse.model_validate(response.json())
    expected = expected_title.casefold()

    for book in result.books:
        if expected in book.title.casefold():
            return book

    titles = [book.title for book in result.books]
    raise AssertionError(
        f"Book {expected_title!r} was not found for query {query!r}. "
        f"Returned titles: {titles}"
    )


@pytest.mark.e2e
@pytest.mark.parametrize(
    "catalog_id,query,expected_title",
    CATALOG_CASES,
)
def test_book_can_be_found_in_catalog(
    api,
    flow,
    catalog_id,
    query,
    expected_title,
):
    user = flow.create_configured_pocketbook_user(
        catalog_id=catalog_id,
    )

    book = _find_expected_book(
        api=api,
        uid=user.uid,
        query=query,
        expected_title=expected_title,
    )

    assert book.url.startswith("https://")


@pytest.mark.e2e
@pytest.mark.parametrize(
    "catalog_id,query,expected_title",
    CATALOG_CASES,
)
def test_book_can_be_downloaded_from_source(
    api,
    flow,
    catalog_id,
    query,
    expected_title,
):
    user = flow.create_configured_pocketbook_user(
        catalog_id=catalog_id,
    )

    book = _find_expected_book(
        api=api,
        uid=user.uid,
        query=query,
        expected_title=expected_title,
    )

    response = api.download(
        uid=user.uid,
        url=book.url,
    )

    assert response.status_code == 200
    assert response.headers["Content-Type"].startswith("application/epub")
    assert len(response.content) > 1000
    assert response.content.startswith(b"PK")
