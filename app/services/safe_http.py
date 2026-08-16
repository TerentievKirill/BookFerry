from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urljoin, urlparse

import requests

# Do not allow an external server to redirect requests indefinitely.
MAX_REDIRECTS = 5


def validate_public_url(url: str) -> None:
    parsed = urlparse(url)
    # BookFerry only needs normal web URLs.
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Only http:// and https:// URLs are allowed")

    if not parsed.hostname:
        raise ValueError("URL does not contain a hostname")

        # Credentials inside URLs are not needed here and make validation harder.
        # Example: https://user:password@example.com/
    if parsed.username or parsed.password:
        raise ValueError("URLs with username or password are not supported")

    try:
        # Resolve the hostname before making the request.
        # A public-looking hostname may still point to localhost or a private network.
        addresses = socket.getaddrinfo(
            parsed.hostname,
            parsed.port or (443 if parsed.scheme == "https" else 80),
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror as error:
        raise ValueError("Could not resolve server address") from error

    if not addresses:
        raise ValueError("Could not resolve server address")
    # Check every IP returned by DNS.
    # If even one address is private or local, reject the URL.
    for address in addresses:
        raw_ip = address[4][0]
        try:
            ip = ipaddress.ip_address(raw_ip)
        except ValueError as error:
            raise ValueError("Invalid server address") from error

         # is_global excludes localhost, private networks, link-local addresses,
        # multicast and other addresses that should not be reachable through BookFerry.
        if not ip.is_global:
            raise ValueError("Local and private network addresses are not allowed")


def safe_get(
    url: str,
    *,
    params: dict | None = None,
    timeout=(10, 60),
    stream: bool = False,
    headers: dict | None = None,
) -> requests.Response:
    # Redirects are handled manually because requests would normally follow them
    # automatically. Every new URL must pass the same public-address validation.
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
        # Query parameters belong only to the original request.
        # A redirect already gives us the complete URL for the next request.
        current_params = None

        if response.is_redirect or response.is_permanent_redirect:
            location = response.headers.get("Location")
            # A redirect without Location is malformed, but return it to the
            # caller so normal HTTP status handling can decide what to do.
            if not location:
                return response

            # Location may be either an absolute URL or a relative path.
            current_url = urljoin(response.url, location)
            # We are not going to read this response body.
            response.close()
            continue

        return response

    raise ValueError("Too many redirects")
