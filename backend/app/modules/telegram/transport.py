"""Transport for a self-hosted Telegram Bot API server."""

from pathlib import Path

from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import SimpleFilesPathWrapper, TelegramAPIServer

from app.core.config import TELEGRAM_API_URL, TELEGRAM_FILES_DIR


class TelegramFiles(SimpleFilesPathWrapper):
    """Map getFile paths to the read-only Bot API cache on this host."""

    def to_local(self, path: Path | str) -> Path:
        local = Path(super().to_local(path)).resolve()
        if not local.is_relative_to(self.local_path.resolve()):
            raise ValueError("Telegram file is outside the configured cache")
        return local


def create_telegram_bot(token: str) -> Bot:
    api = TelegramAPIServer.from_base(
        TELEGRAM_API_URL, is_local=True,
        wrap_local_file=TelegramFiles(Path("/var/lib/telegram-bot-api"), TELEGRAM_FILES_DIR),
    )
    return Bot(token=token, session=AiohttpSession(api=api))
