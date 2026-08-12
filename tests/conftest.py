from pathlib import Path

import pytest

from tests.framework.api import BookFerryApi
from tests.framework.flows import BookFerryFlow


TEST_DB_PATH = Path(__file__).parent / "data" / "bookferry_test.db"


pytest_plugins = [
    "tests.fixtures.users",
]


def pytest_addoption(parser):
    parser.addoption(
        "--base-url",
        default="http://127.0.0.1:8000",
        help="BookFerry API base URL",
    )


@pytest.fixture(scope="session")
def test_db_path() -> Path:
    return TEST_DB_PATH


@pytest.fixture(scope="session")
def base_url(request) -> str:
    return request.config.getoption("--base-url").rstrip("/")


@pytest.fixture(scope="session")
def api(base_url) -> BookFerryApi:
    return BookFerryApi(base_url)


@pytest.fixture
def flow(api) -> BookFerryFlow:
    return BookFerryFlow(api)