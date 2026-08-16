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
