import pytest

from tests.framework.models import TelegramUser, User


TELEGRAM_TEST_USER_ID = 987654321


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


@pytest.fixture
def telegram_user(api) -> TelegramUser:
    response = api.set_telegram_catalog(
        TELEGRAM_TEST_USER_ID,
        catalog_id=1,
    )

    assert response.status_code == 200

    response = api.get_telegram_user(TELEGRAM_TEST_USER_ID)

    assert response.status_code == 200

    user = TelegramUser.model_validate(response.json())

    assert user.telegram_id == TELEGRAM_TEST_USER_ID
    assert user.uid

    return user
