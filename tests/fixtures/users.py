import pytest

from tests.framework.models import User


@pytest.fixture
def pocketbook_user(api) -> User:
    response = api.register_user(
        client_type="pocketbook",
    )

    assert response.status_code == 200

    user = User.model_validate(response.json())

    assert user.client_type == "pocketbook"
    assert user.uid

    return user


@pytest.fixture
def configured_pocketbook_user(api, pocketbook_user) -> User:
    catalog_response = api.set_catalog(
        pocketbook_user.uid,
        catalog_id=1,
    )

    assert catalog_response.status_code == 200

    response = api.get_user(pocketbook_user.uid)

    assert response.status_code == 200

    return User.model_validate(response.json())
