from __future__ import annotations

import requests


class BookFerryApi:
    def __init__(self, base_url: str, timeout: int = 15):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()

    def _request(self, method: str, path: str, **kwargs) -> requests.Response:
        return self.session.request(
            method=method,
            url=f"{self.base_url}{path}",
            timeout=self.timeout,
            **kwargs,
        )

    def health(self) -> requests.Response:
        return self._request("GET", "/health")

    def catalogs(self) -> requests.Response:
        return self._request("GET", "/catalogs")

    def register_user(
        self,
        client_type: str,
        external_id: str | None = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            "/users/register",
            json={
                "client_type": client_type,
                "external_id": external_id,
            },
        )

    def get_user(self, uid: str) -> requests.Response:
        return self._request("GET", f"/users/{uid}")

    def set_catalog(
        self,
        uid: str,
        catalog_id: int,
    ) -> requests.Response:
        return self._request(
            "PATCH",
            f"/users/{uid}/catalog",
            json={"catalog_id": catalog_id},
        )

    def set_emails(
        self,
        uid: str,
        emails: str,
    ) -> requests.Response:
        return self._request(
            "PATCH",
            f"/users/{uid}/emails",
            json={"emails": emails},
        )

    def set_subject(
        self,
        uid: str,
        subject: str | None,
    ) -> requests.Response:
        return self._request(
            "PATCH",
            f"/users/{uid}/subject",
            json={"subject": subject},
        )

    def search(
        self,
        uid: str,
        query: str,
        page_url: str | None = None,
    ) -> requests.Response:
        params = {
            "uid": uid,
            "query": query,
        }

        if page_url is not None:
            params["page_url"] = page_url

        return self._request(
            "GET",
            "/search",
            params=params,
        )

    def download(
        self,
        uid: str,
        url: str,
    ) -> requests.Response:
        return self._request(
            "GET",
            "/download",
            params={
                "uid": uid,
                "url": url,
            },
        )

    def report_download(
        self,
        uid: str,
        status: str,
        *,
        bytes_received: int = 0,
        attempts: int = 1,
        duration_ms: int = 0,
        http_status: int = 0,
        net_status: int = 0,
        title: str | None = None,
        error: str | None = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            "/download/client-result",
            params={
                "uid": uid,
                "status": status,
                "bytes": bytes_received,
                "attempts": attempts,
                "duration_ms": duration_ms,
                "http_status": http_status,
                "net_status": net_status,
                "title": title,
                "error": error,
            },
        )