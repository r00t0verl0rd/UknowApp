"""Тесты облачного и локального Telegram API."""

import asyncio

from app.modules.telegram import transport


def test_cloud_uses_official_api_without_local_cache(monkeypatch):
    monkeypatch.setenv("TELEGRAM_API_MODE", "cloud")
    monkeypatch.setattr(transport, "TELEGRAM_API_URL", "http://local-api:8081")
    bot = transport.create_telegram_bot("123:" + "a" * 32)
    try:
        assert bot.session.api.api_url(bot.token, "getMe").startswith(
            "https://api.telegram.org/bot"
        )
        assert not bot.session.api.is_local
    finally:
        asyncio.run(bot.session.close())


def test_local_keeps_mounted_file_transport(monkeypatch):
    monkeypatch.setenv("TELEGRAM_API_MODE", "local")
    monkeypatch.setattr(transport, "TELEGRAM_API_URL", "http://local-api:8081")
    bot = transport.create_telegram_bot("123:" + "a" * 32)
    try:
        assert bot.session.api.api_url(bot.token, "getMe").startswith(
            "http://local-api:8081/"
        )
        assert bot.session.api.is_local
    finally:
        asyncio.run(bot.session.close())


def test_rejects_unknown_mode(monkeypatch):
    monkeypatch.setenv("TELEGRAM_API_MODE", "unsupported")
    try:
        transport.create_telegram_bot("123:" + "a" * 32)
    except ValueError as exc:
        assert "TELEGRAM_API_MODE" in str(exc)
    else:
        raise AssertionError("Invalid mode must be rejected")
