"""Проверки паролей, источников запросов и сети."""

import hashlib
import ipaddress
import secrets

from fastapi import HTTPException, Request

from .config import ADMIN_PASSWORD, ADMIN_USERNAME, ALLOWED_ORIGINS, TRUSTED_PROXY_IPS

def verify_admin(username: str, password: str) -> bool:
    # Не разрешаем вход с паролем из шаблона.
    if ADMIN_PASSWORD in {"change-me-now", "replace-with-a-long-random-password"}:
        return False
    return (
        secrets.compare_digest(username.encode("utf-8"), ADMIN_USERNAME.encode("utf-8"))
        and secrets.compare_digest(password.encode("utf-8"), ADMIN_PASSWORD.encode("utf-8"))
    )


# Храним только PBKDF2-хеш с уникальной солью, а не исходный код доступа.
def hash_web_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 310_000)
    return salt.hex() + ":" + digest.hex()


# Сравниваем вычисленный хеш с сохранённым значением без утечки через время сравнения.
def verify_web_password(password: str, stored: str | None) -> bool:
    if not stored or ":" not in stored:
        return False
    try:
        salt_hex, digest_hex = stored.split(":", 1)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
    except ValueError:
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 310_000)
    return secrets.compare_digest(actual, expected)


def verify_request_origin(request: Request) -> None:
    """Запретить опасные запросы с чужого сайта (CSRF)."""
    if request.method.upper() in {"GET", "HEAD", "OPTIONS"}:
        return
    origin = request.headers.get("origin")
    if not origin:
        # Проверяем Origin только для браузерных запросов с cookie.
        return
    origin = origin.strip().rstrip("/")
    current_origin = str(request.base_url).rstrip("/")
    allowed = {item.strip().rstrip("/") for item in ALLOWED_ORIGINS if item.strip()}
    allowed.add(current_origin)
    if origin not in allowed:
        raise HTTPException(status_code=403, detail="Запрос с этого источника запрещён")


def _client_ip(request: Request) -> str:
    peer = request.client.host if request.client else "unknown"
    if peer not in TRUSTED_PROXY_IPS:
        return peer

    for header in ("cf-connecting-ip", "x-forwarded-for"):
        forwarded = request.headers.get(header, "").split(",")[0].strip()
        try:
            return str(ipaddress.ip_address(forwarded))
        except ValueError:
            continue
    return peer


def normalize_login(value: str | None) -> str:
    """Нормализовать логин для поиска и проверки уникальности."""
    return (value or "").strip().casefold()
