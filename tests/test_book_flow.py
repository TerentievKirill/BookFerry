def test_pocketbook_user_can_find_book(flow):
    user = flow.create_configured_user(
        client_type="pocketbook",
        catalog_id=1,
    )

    book = flow.find_first_book(
        uid=user.uid,
        query="анекдот",
    )

    assert book.title
    assert book.url