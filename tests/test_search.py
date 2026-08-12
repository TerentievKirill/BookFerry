from tests.framework.models import SearchResponse


def test_user_can_search_books(api, configured_pocketbook_user):
    response = api.search(
        uid=configured_pocketbook_user.uid,
        query="Лабиринт отражений",
    )

    assert response.status_code == 200

    result = SearchResponse.model_validate(response.json())

    assert result.books


def test_search_requires_existing_user(api):
    response = api.search(
        uid="unknown-autotest-user",
        query="Лабиринт отражений",
    )

    assert response.status_code == 404