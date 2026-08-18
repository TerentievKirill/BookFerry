import allure

from tests.fixtures.users import TELEGRAM_TEST_USER_ID


# Minimal smoke tests for the main user scenarios. They are intentionally small:
# the goal is to catch commits that break basic behavior, not to cover every case.
@allure.parent_suite("BookFerry")
@allure.suite("Smoke")
@allure.title("PocketBook user can find a book")
def test_pocketbook_user_can_find_book(flow):
    user = flow.create_configured_pocketbook_user(
        catalog_id=3,
    )

    book = flow.find_first_book(
        uid=user.uid,
        query="Лабиринт отражений",
    )

    assert book.title
    assert book.url


@allure.parent_suite("BookFerry")
@allure.suite("Smoke")
@allure.title("Telegram user can find a book")
def test_telegram_user_can_find_book(flow):
    user = flow.create_configured_telegram_user(
        telegram_id=TELEGRAM_TEST_USER_ID,
        catalog_id=3,
    )

    book = flow.find_first_book(
        uid=user.uid,
        query="Лабиринт отражений",
    )

    assert book.title
    assert book.url
