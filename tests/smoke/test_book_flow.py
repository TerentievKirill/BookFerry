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


def test_telegram_user_can_find_book(flow):
    telegram_id = 987654321

    flow.create_configured_telegram_user(
        telegram_id=telegram_id,
        catalog_id=3,
    )

    book = flow.find_first_telegram_book(
        telegram_id=telegram_id,
        query="Лабиринт отражений",
    )

    assert book.title
    assert book.url
