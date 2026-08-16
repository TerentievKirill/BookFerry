from tests.framework.api import BookFerryApi
from tests.framework.models import Book, SearchResponse, User


class BookFerryFlow:
    def __init__(self, api: BookFerryApi):
        self.api = api

    def create_configured_pocketbook_user(
        self,
        catalog_id: int,
    ) -> User:
        response = self.api.register_user(
            client_type="pocketbook",
        )
        response.raise_for_status()

        user = User.model_validate(response.json())

        response = self.api.set_catalog(user.uid, catalog_id)
        response.raise_for_status()

        response = self.api.get_user(user.uid)
        response.raise_for_status()

        return User.model_validate(response.json())

    def find_first_book(
        self,
        uid: str,
        query: str,
    ) -> Book:
        response = self.api.search(uid, query)
        response.raise_for_status()

        search_result = SearchResponse.model_validate(response.json())

        if not search_result.books:
            raise AssertionError(
                f"No books found for query: {query!r}"
            )

        return search_result.books[0]
