from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urljoin, urlparse

import requests


MAX_REDIRECTS = 5


def validate_public_url(url: str) -> None:
    parsed = urlparse(url)

    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Разрешены только http:// и https:// адреса")

    if not parsed.hostname:
        raise ValueError("В URL не указан сервер")

    if parsed.username or parsed.password:
        raise ValueError("URL с логином или паролем не поддерживается")

    try:
        addresses = socket.getaddrinfo(
            parsed.hostname,
            parsed.port or (443 if parsed.scheme == "https" else 80),
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror as error:
        raise ValueError("Не удалось определить адрес OPDS-сервера") from error

    if not addresses:
        raise ValueError("Не удалось определить адрес OPDS-сервера")

    for address in addresses:
        raw_ip = address[4][0]
        try:
            ip = ipaddress.ip_address(raw_ip)
        except ValueError as error:
            raise ValueError("Некорректный адрес OPDS-сервера") from error

        if not ip.is_global:
            raise ValueError("Адреса локальной и внутренней сети запрещены")


def safe_get(
    url: str,
    *,
    params: dict | None = None,
    timeout=(10, 60),
    stream: bool = False,
    headers: dict | None = None,
) -> requests.Response:
    current_url = url
    current_params = params

    for _ in range(MAX_REDIRECTS + 1):
        validate_public_url(current_url)

        response = requests.get(
            current_url,
            params=current_params,
            timeout=timeout,
            stream=stream,
            headers=headers,
            allow_redirects=False,
        )
        current_params = None

        if response.is_redirect or response.is_permanent_redirect:
            location = response.headers.get("Location")
            if not location:
                return response

            current_url = urljoin(response.url, location)
            response.close()
            continue

        return response

    raise ValueError("Слишком много перенаправлений")
