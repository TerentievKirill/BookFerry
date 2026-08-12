import uuid

import pytest


@pytest.fixture
def pocketbook_user(api):
    external_id = f"autotest-{uuid.uuid4()}"

    return api.register_user(
        client_type="pocketbook",
        external_id=external_id,
    )


@pytest.fixture
def configured_pocketbook_user(api, pocketbook_user):
    api.set_catalog(pocketbook_user.uid, catalog_id=1)
    api.set_emails(
        pocketbook_user.uid,
        "autotest@pbsync.com",
    )

    return api.get_user(pocketbook_user.uid)