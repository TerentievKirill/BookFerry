"""Focused retry tests: no real network requests."""
import requests
import pytest

from app.services import download


def _response(status: int) -> requests.Response:
    response = requests.Response()
    response.status_code = status
    response.url = "http://flibusta.is/b/312963/epub"
    response._content = b"test"
    return response


def test_retries_gateway_timeout_then_succeeds(monkeypatch):
    calls = []
    delays = []
    outcomes = [_response(504), _response(503), _response(200)]

    def fake_get(url, **kwargs):
        calls.append(kwargs)
        return outcomes.pop(0)

    monkeypatch.setattr(download, "safe_get", fake_get)
    monkeypatch.setattr(download.time, "sleep", delays.append)

    response = download._get_book_response("http://flibusta.is/b/312963/epub", stream=True)

    assert response.status_code == 200
    assert len(calls) == 3
    assert all(call["stream"] is True for call in calls)
    assert delays == [5, 5]


def test_retries_connection_error(monkeypatch):
    calls = 0
    delays = []

    def fake_get(url, **kwargs):
        nonlocal calls
        calls += 1
        if calls < 3:
            raise requests.ConnectionError("Connection reset by peer")
        return _response(200)

    monkeypatch.setattr(download, "safe_get", fake_get)
    monkeypatch.setattr(download.time, "sleep", delays.append)

    assert download._get_book_response("http://example.org/book", stream=False).status_code == 200
    assert calls == 3
    assert delays == [5, 5]


def test_does_not_retry_not_found(monkeypatch):
    calls = 0

    def fake_get(url, **kwargs):
        nonlocal calls
        calls += 1
        return _response(404)

    monkeypatch.setattr(download, "safe_get", fake_get)
    monkeypatch.setattr(download.time, "sleep", lambda _: pytest.fail("Unexpected retry"))

    with pytest.raises(requests.HTTPError):
        download._get_book_response("http://example.org/missing", stream=False)
    assert calls == 1


def test_stops_after_seven_attempts(monkeypatch):
    calls = 0
    delays = []

    def fake_get(url, **kwargs):
        nonlocal calls
        calls += 1
        return _response(504)

    monkeypatch.setattr(download, "safe_get", fake_get)
    monkeypatch.setattr(download.time, "sleep", delays.append)

    with pytest.raises(requests.HTTPError):
        download._get_book_response("http://example.org/book", stream=False)

    assert calls == 7
    assert delays == [5] * 6
