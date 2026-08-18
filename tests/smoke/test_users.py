import allure
import pytest

from tests.fixtures.users import TELEGRAM_TEST_USER_ID
from tests.framework.models import TelegramUser, User


# Minimal smoke tests for user management. They are intentionally small:
# the goal is to catch commits that break basic behavior, not to cover every case.
@allure.title("PocketBook user can be registered")
def test_pocketbook_user_can_be_registered(api):
    response = api.register_user(
        client_type="pocketbook",
    )

    assert response.status_code == 200

    user = User.model_validate(response.json())

    assert user.client_type == "pocketbook"
    assert user.external_id is None
    assert user.uid


@allure.title("Telegram user can be created")
def test_telegram_user_can_be_created(api):
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


@allure.title("Invalid user type is rejected")
@pytest.mark.parametrize(
    "client_type",
    [
        pytest.param("", id="empty"),
        pytest.param("android", id="unknown"),
    ],
)
def test_user_registration_rejects_invalid_client_type(api, client_type):
    response = api.register_user(
        client_type=client_type,
    )

    assert response.status_code == 400


@allure.title("PocketBook catalog can be changed")
def test_pocketbook_catalog_can_be_changed(api, pocketbook_user):
    uid = pocketbook_user.uid

    catalog_response = api.set_catalog(uid, 3)

    assert catalog_response.status_code == 200

    response = api.get_user(uid)

    assert response.status_code == 200

    user = User.model_validate(response.json())

    assert user.catalog_id == 3


@allure.title("Telegram catalog can be changed")
def test_telegram_catalog_can_be_changed(api, telegram_user):
    telegram_id = telegram_user.telegram_id

    catalog_response = api.set_telegram_catalog(telegram_id, 3)

    assert catalog_response.status_code == 200

    response = api.get_telegram_user(telegram_id)

    assert response.status_code == 200

    user = TelegramUser.model_validate(response.json())

    assert user.catalog_id == 3


@allure.title("Unknown user returns 404")
def test_unknown_user_returns_404(api):
    response = api.get_user("unknown-autotest-user")

    assert response.status_code == 404


@allure.title("Unknown Telegram user returns 404")
def test_unknown_telegram_user_returns_404(api):
    response = api.get_telegram_user(2147483647)

    assert response.status_code == 404
