"""Telegram Bot API transport, isolated from UknowApp business logic."""

from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession


def create_telegram_bot(token: str, proxy_url: str = "") -> Bot:
    """Create the usual aiogram client, optionally routing all API/file traffic through an HTTP proxy."""
    session = AiohttpSession(proxy=proxy_url or None)
    return Bot(token=token, session=session)
