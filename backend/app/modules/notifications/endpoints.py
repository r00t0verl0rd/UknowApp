"""Проверка адресов Web Push."""

import ipaddress
import socket
from urllib.parse import urlsplit

_ALLOWED_HOSTS = {
    "fcm.googleapis.com",
    "web.push.apple.com",
    "updates.push.services.mozilla.com",
}
_ALLOWED_SUFFIXES = (".push.services.mozilla.com", ".notify.windows.com")


def is_safe_push_endpoint(endpoint: str) -> bool:
    """Разрешать известные Web Push-сервисы с публичными IP."""
    try:
        parsed = urlsplit(endpoint)
        hostname = parsed.hostname
        if (
            parsed.scheme != "https"
            or not hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port not in (None, 443)
            or parsed.fragment
            or parsed.query
            or not (hostname in _ALLOWED_HOSTS or hostname.endswith(_ALLOWED_SUFFIXES))
        ):
            return False
        addresses = {
            ipaddress.ip_address(result[4][0])
            for result in socket.getaddrinfo(hostname, parsed.port or 443, type=socket.SOCK_STREAM)
        }
        return bool(addresses) and all(address.is_global for address in addresses)
    except (OSError, ValueError):
        return False
