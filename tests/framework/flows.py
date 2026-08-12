from tests.framework.api import BookFerryApi
from tests.framework.models import Book, SearchResponse, User


class BookFerryFlow:
    def __init__(self, api: BookFerryApi):
        self.api = api

    def create_configured_user(
        self,
        client_type: str,
        catalog_id: int,
        *,
        external_id: str | None = None,
        emails: str | None = None,
        subject: str | None = None,
    ) -> User:
        response = self.api.register_user(
            client_type=client_type,
            external_id=external_id,
        )
        response.raise_for_status()

        user = User.model_validate(response.json())

        response = self.api.set_catalog(user.uid, catalog_id)
        response.raise_for_status()

        if emails is not None:
            response = self.api.set_emails(user.uid, emails)
            response.raise_for_status()

        if subject is not None:
            response = self.api.set_subject(user.uid, subject)
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