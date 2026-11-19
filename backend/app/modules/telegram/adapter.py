"""Telegram outbound adapter. aiogram stays inside this provider boundary."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from aiogram import Bot
from aiogram.types import BufferedInputFile

from ...infrastructure.storage.media import MEDIA_DIR
from ..communication.contracts import (
    DeliveryResult,
    MessageKind,
    MessengerCapabilities,
    MessengerPlatform,
    OutboundMessage,
)

logger = logging.getLogger(__name__)


class TelegramAdapter:
    """Deliver normalized application messages through the Telegram Bot API."""

    platform = MessengerPlatform.TELEGRAM

    def __init__(self, bot: Bot, media_dir: Path = MEDIA_DIR) -> None:
        self._bot = bot
        self._media_dir = media_dir

    @property
    def capabilities(self) -> MessengerCapabilities:
        return MessengerCapabilities(
            text=True,
            attachments=True,
            delete_messages=True,
            interactive_messages=True,
            group_chats=True,
            threaded_chats=True,
        )

    @staticmethod
    def _chat_kwargs(message: OutboundMessage) -> dict:
        kwargs = {"chat_id": int(message.external_chat_id)}
        if message.external_thread_id is not None:
            kwargs["message_thread_id"] = int(message.external_thread_id)
        return kwargs

    def _media_path(self, message: OutboundMessage) -> Path:
        if message.media is None:
            raise ValueError("Outbound media is required")
        root = self._media_dir.resolve()
        path = (root / message.media.storage_key).resolve()
        if root not in path.parents or not path.is_file():
            raise FileNotFoundError("Stored attachment is unavailable")
        return path

    async def _send_native_media(
        self, message: OutboundMessage, content: bytes, kwargs: dict
    ):
        upload = BufferedInputFile(
            content, filename=message.media.file_name
        )
        kind = message.content_type
        if kind == MessageKind.PHOTO and len(content) <= 10 * 1024 * 1024:
            return await self._bot.send_photo(photo=upload, **kwargs)
        if kind == MessageKind.ANIMATION:
            return await self._bot.send_animation(animation=upload, **kwargs)
        if kind == MessageKind.VIDEO:
            return await self._bot.send_video(video=upload, **kwargs)
        if kind == MessageKind.VOICE:
            return await self._bot.send_voice(voice=upload, **kwargs)
        if kind == MessageKind.AUDIO:
            return await self._bot.send_audio(audio=upload, **kwargs)
        return await self._bot.send_document(document=upload, **kwargs)

    async def send(self, message: OutboundMessage) -> DeliveryResult:
        if message.platform != self.platform:
            raise ValueError("Telegram adapter received a message for another platform")

        kwargs = self._chat_kwargs(message)
        if message.content_type == MessageKind.TEXT:
            sent = await self._bot.send_message(
                text=message.text, **kwargs
            )
        else:
            path = self._media_path(message)
            content = path.read_bytes()
            if message.text:
                kwargs["caption"] = message.text
            try:
                sent = await self._send_native_media(
                    message, content, kwargs
                )
            except Exception as native_error:
                # Preserve the previous web-panel behavior: when Telegram
                # rejects a native media type, retry the same file as a document.
                logger.info(
                    "Native Telegram media send failed; retrying as document "
                    "(kind=%s error_type=%s)",
                    message.content_type.value,
                    type(native_error).__name__,
                )
                upload = BufferedInputFile(
                    content, filename=message.media.file_name
                )
                sent = await self._bot.send_document(
                    document=upload, **kwargs
                )

        return DeliveryResult(
            platform=self.platform,
            external_chat_id=message.external_chat_id,
            external_message_id=str(sent.message_id),
            delivered_at=datetime.now(timezone.utc),
        )

    async def delete_message(
        self, external_chat_id: str, external_message_id: str
    ) -> None:
        await self._bot.delete_message(
            chat_id=int(external_chat_id),
            message_id=int(external_message_id),
        )
