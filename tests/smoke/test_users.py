import uuid

import pytest

from tests.framework.models import User


@pytest.mark.parametrize(
    "client_type",
    [
        pytest.param("telegram", id="telegram"),
        pytest.param("pocketbook", id="pocketbook"),
        pytest.param("flutter", id="flutter"),
    ],
)
def test_user_can_be_registered(api, client_type):
    external_id = f"autotest-{uuid.uuid4()}"

    response = api.register_user(
        client_type=client_type,
        external_id=external_id,
    )

    assert response.status_code == 201

    user = User.model_validate(response.json())

    assert user.client_type == client_type
    assert user.external_id == external_id
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
        external_id=f"autotest-{uuid.uuid4()}",
    )

    assert response.status_code == 422


def test_user_profile_can_be_updated(api, pocketbook_user):
    uid = pocketbook_user.uid

    catalog_response = api.set_catalog(uid, 1)
    email_response = api.set_emails(uid, "autotest@pbsync.com")
    subject_response = api.set_subject(uid, "BookFerry autotest")

    assert catalog_response.status_code == 200
    assert email_response.status_code == 200
    assert subject_response.status_code == 200

    response = api.get_user(uid)

    assert response.status_code == 200

    user = User.model_validate(response.json())

    assert user.catalog_id == 1
    assert user.emails == "autotest@pbsync.com"
    assert user.subject == "BookFerry autotest"


def test_unknown_user_returns_404(api):
    response = api.get_user("unknown-autotest-user")

    assert response.status_code == 404