import pytest

from tests.framework.models import User


def test_pocketbook_user_can_be_registered(api):
    response = api.register_user(
        client_type="pocketbook",
    )

    assert response.status_code == 200

    user = User.model_validate(response.json())

    assert user.client_type == "pocketbook"
    assert user.external_id is None
    assert user.uid


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


def test_pocketbook_catalog_can_be_changed(api, pocketbook_user):
    uid = pocketbook_user.uid

    catalog_response = api.set_catalog(uid, 3)

    assert catalog_response.status_code == 200

    response = api.get_user(uid)

    assert response.status_code == 200

    user = User.model_validate(response.json())

    assert user.catalog_id == 3


def test_unknown_user_returns_404(api):
    response = api.get_user("unknown-autotest-user")

    assert response.status_code == 404
