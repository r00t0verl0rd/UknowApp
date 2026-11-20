"""Telegram adapter for normalized inbound and outbound communication."""

from __future__ import annotations

import json
import logging
import mimetypes
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import BufferedInputFile

from app.infrastructure.storage.media import MEDIA_DIR, safe_media_type
from app.models import Message
from app.modules.communication.contracts import (
    DeliveryResult,
    InboundLocation,
    InboundMedia,
    InboundMessage,
    InboundPoll,
    MessageKind,
    MessengerCapabilities,
    MessengerPlatform,
    MessengerError,
    OutboundMessage,
)

logger = logging.getLogger(__name__)


class TelegramAdapter:
    """Translate Telegram updates and Bot API operations at the provider edge."""

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

    def normalize_event(self, payload: Mapping[str, object]) -> Sequence[InboundMessage]:
        """Convert a plain Telegram event mapping into normalized application data."""
        chat = payload.get("chat") if isinstance(payload.get("chat"), Mapping) else {}
        sender = payload.get("from_user") if isinstance(payload.get("from_user"), Mapping) else {}
        sender_chat = payload.get("sender_chat") if isinstance(payload.get("sender_chat"), Mapping) else {}
        media_data = payload.get("media") if isinstance(payload.get("media"), Mapping) else {}
        chat_id = payload.get("chat_id", chat.get("id"))
        message_id = payload.get("message_id")
        if chat_id is None or message_id is None:
            return ()

        try:
            content_type = MessageKind(str(payload.get("content_type") or "unsupported"))
        except ValueError:
            content_type = MessageKind.UNSUPPORTED

        location_data = payload.get("location") if isinstance(payload.get("location"), Mapping) else None
        location = None
        if location_data and location_data.get("latitude") is not None and location_data.get("longitude") is not None:
            location = InboundLocation(
                latitude=float(location_data["latitude"]),
                longitude=float(location_data["longitude"]),
            )
        poll_data = payload.get("poll") if isinstance(payload.get("poll"), Mapping) else None
        poll = (
            InboundPoll(
                question=str(poll_data.get("question") or ""),
                options=tuple(str(item) for item in (poll_data.get("options") or ())),
            )
            if poll_data else None
        )
        occurred_at = payload.get("date")
        if not isinstance(occurred_at, datetime):
            occurred_at = None

        external_chat_id = str(chat_id)
        external_message_id = str(message_id)
        user_id = payload.get("user_id", sender.get("id"))
        sender_chat_id = payload.get("sender_chat_id", sender_chat.get("id"))
        username = payload.get("username", sender.get("username"))
        chat_type = payload.get("chat_type", chat.get("type", "private"))
        thread_id = payload.get("thread_id")

        return (InboundMessage(
            platform=self.platform,
            event_id=str(payload.get("event_id") or f"telegram:{external_chat_id}:{external_message_id}"),
            external_user_id=str(user_id) if user_id is not None else None,
            external_chat_id=external_chat_id,
            external_message_id=external_message_id,
            content_type=content_type,
            text=str(payload.get("text") or ""),
            caption=str(payload.get("caption") or ""),
            media=(
                InboundMedia(
                    file_name=str(media_data["file_name"]) if media_data.get("file_name") else None,
                    mime_type=str(media_data["mime_type"]) if media_data.get("mime_type") else None,
                    file_size=int(media_data["file_size"]) if media_data.get("file_size") is not None else None,
                    provider_file_id=str(media_data["file_id"]) if media_data.get("file_id") else None,
                    provider_unique_file_id=str(media_data["file_unique_id"]) if media_data.get("file_unique_id") else None,
                    is_video=bool(media_data.get("is_video", False)),
                    is_animated=bool(media_data.get("is_animated", False)),
                )
                if media_data else None
            ),
            occurred_at=occurred_at,
            external_thread_id=str(thread_id) if thread_id is not None else None,
            sender_username=str(username) if username else None,
            sender_chat_id=str(sender_chat_id) if sender_chat_id is not None else None,
            chat_type=str(chat_type),
            chat_is_forum=bool(payload.get("chat_is_forum", chat.get("is_forum", False))),
            chat_title=str(payload.get("chat_title") or chat.get("title")) if payload.get("chat_title") or chat.get("title") else None,
            location=location,
            poll=poll,
            contact_present=bool(payload.get("contact_present", payload.get("contact") is not None)),
        ),)

    def normalize_message(self, message) -> InboundMessage:
        """Normalize aiogram's message object without leaking it into the app workflow."""
        media_data = {}
        for field in (
            "photo", "document", "audio", "video", "voice",
            "video_note", "sticker", "animation",
        ):
            item = getattr(message, field, None)
            if not item:
                continue
            if isinstance(item, list):
                item = item[-1]
            media_data = {
                "file_id": getattr(item, "file_id", None),
                "file_unique_id": getattr(item, "file_unique_id", None),
                "file_name": getattr(item, "file_name", None),
                "mime_type": getattr(item, "mime_type", None),
                "file_size": getattr(item, "file_size", None),
                "is_video": bool(getattr(item, "is_video", False)),
                "is_animated": bool(getattr(item, "is_animated", False)),
            }
            break

        from_user = getattr(message, "from_user", None)
        sender_chat = getattr(message, "sender_chat", None)
        location_obj = getattr(message, "location", None)
        poll_obj = getattr(message, "poll", None)
        chat = message.chat
        normalized = self.normalize_event({
            "message_id": message.message_id,
            "event_id": f"telegram:{chat.id}:{message.message_id}",
            "user_id": getattr(from_user, "id", None),
            "username": getattr(from_user, "username", None),
            "chat_id": chat.id,
            "chat_type": chat.type,
            "chat_is_forum": bool(getattr(chat, "is_forum", False)),
            "chat_title": getattr(chat, "title", None),
            "sender_chat_id": getattr(sender_chat, "id", None),
            "thread_id": getattr(message, "message_thread_id", None),
            "content_type": getattr(getattr(message, "content_type", None), "value", "unsupported"),
            "text": message.text or "",
            "caption": message.caption or "",
            "date": message.date,
            "media": media_data,
            "location": (
                {"latitude": location_obj.latitude, "longitude": location_obj.longitude}
                if location_obj else None
            ),
            "poll": (
                {
                    "question": poll_obj.question,
                    "options": [option.text for option in poll_obj.options],
                }
                if poll_obj else None
            ),
            "contact_present": bool(getattr(message, "contact", None)),
        })
        if not normalized:
            raise ValueError("Telegram message has no chat or message identifier")
        return normalized[0]

    @staticmethod
    def _chat_kwargs(external_chat_id: str, thread_id: str | None = None) -> dict:
        kwargs = {"chat_id": int(external_chat_id)}
        if thread_id is not None:
            kwargs["message_thread_id"] = int(thread_id)
        return kwargs

    async def send_text(
        self, external_chat_id: str, text: str, thread_id: str | None = None,
    ) -> str:
        try:
            sent = await self._bot.send_message(
                text=text, **self._chat_kwargs(external_chat_id, thread_id),
            )
        except TelegramAPIError as exc:
            raise MessengerError("send_text", exc) from exc
        return str(sent.message_id)

    async def copy_message(
        self,
        source_chat_id: str,
        source_message_id: str,
        target_chat_id: str,
        target_thread_id: str | None = None,
        caption: str | None = None,
    ) -> str:
        kwargs = {
            "from_chat_id": int(source_chat_id),
            "message_id": int(source_message_id),
            **self._chat_kwargs(target_chat_id, target_thread_id),
        }
        if caption is not None:
            kwargs["caption"] = caption
        try:
            copied = await self._bot.copy_message(**kwargs)
        except TelegramAPIError as exc:
            raise MessengerError("copy_message", exc) from exc
        return str(copied.message_id)

    async def archive_media(self, inbound: InboundMessage, row: Message) -> None:
        """Download Telegram media and persist an application-owned file copy."""
        item = inbound.media
        if not item or not item.provider_file_id:
            return

        field = inbound.content_type.value
        media_kind = field
        default_mime_type = {
            "photo": "image/jpeg",
            "video": "video/mp4",
            "video_note": "video/mp4",
            "voice": "audio/ogg",
            "animation": "video/mp4",
        }.get(field)
        if field == "sticker":
            if item.is_video:
                media_kind, default_mime_type = "video_sticker", "video/webm"
            elif item.is_animated:
                media_kind, default_mime_type = "animated_sticker", "application/octet-stream"
            else:
                default_mime_type = "image/webp"

        file_name = item.file_name
        if not file_name and field == "sticker":
            file_name = {
                "video_sticker": "Видео-стикер.webm",
                "animated_sticker": "Анимированный-стикер.tgs",
                "sticker": "Стикер.webp",
            }[media_kind]

        metadata = json.loads(row.metadata_json or "{}")
        media = {
            "kind": media_kind,
            "file_id": item.provider_file_id,
            "file_unique_id": item.provider_unique_file_id,
            "file_name": file_name,
            "mime_type": safe_media_type(
                item.mime_type or default_mime_type or mimetypes.guess_type(file_name or "")[0],
            ),
            "file_size": item.file_size,
            "archive_status": "pending",
        }
        metadata["media"] = media
        try:
            if item.file_size and item.file_size > 20 * 1024 * 1024:
                media["archive_status"] = "too_large_for_telegram_download"
            else:
                suffix = Path(file_name or "").suffix.lower()
                if not suffix:
                    suffix = mimetypes.guess_extension(item.mime_type or "") or {
                        "voice": ".ogg", "video_note": ".mp4", "video": ".mp4",
                        "photo": ".jpg", "sticker": ".webp", "animation": ".mp4",
                    }.get(field, ".bin")
                if field == "sticker":
                    suffix = {
                        "video_sticker": ".webm",
                        "animated_sticker": ".tgs",
                        "sticker": ".webp",
                    }[media_kind]
                relative = Path(str(row.conversation_id)) / (uuid.uuid4().hex + suffix[:12])
                root = self._media_dir.resolve()
                target = (root / relative).resolve()
                if root not in target.parents:
                    raise ValueError("Unsafe media archive path")
                target.parent.mkdir(parents=True, exist_ok=True)
                await self._bot.download(item.provider_file_id, destination=target)
                media["local_path"] = relative.as_posix()
                media["archive_status"] = "stored"
        except (TelegramAPIError, OSError, ValueError) as exc:
            logger.warning(
                "Could not archive Telegram media (message_id=%s error_type=%s)",
                row.id, type(exc).__name__,
            )
            media["archive_status"] = "download_failed"
        row.metadata_json = json.dumps(metadata, ensure_ascii=False)

    def _media_path(self, message: OutboundMessage) -> Path:
        if message.media is None:
            raise ValueError("Outbound media is required")
        root = self._media_dir.resolve()
        path = (root / message.media.storage_key).resolve()
        if root not in path.parents or not path.is_file():
            raise FileNotFoundError("Stored attachment is unavailable")
        return path

    async def _send_native_media(
        self, message: OutboundMessage, content: bytes, kwargs: dict,
    ):
        upload = BufferedInputFile(content, filename=message.media.file_name)
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
        kwargs = self._chat_kwargs(message.external_chat_id, message.external_thread_id)
        if message.content_type == MessageKind.TEXT:
            try:
                sent = await self._bot.send_message(text=message.text, **kwargs)
            except TelegramAPIError as exc:
                raise MessengerError("send_message", exc) from exc
        else:
            path = self._media_path(message)
            content = path.read_bytes()
            if message.text:
                kwargs["caption"] = message.text
            try:
                sent = await self._send_native_media(message, content, kwargs)
            except TelegramAPIError as native_error:
                logger.info(
                    "Native Telegram media send failed; retrying as document "
                    "(kind=%s error_type=%s)",
                    message.content_type.value, type(native_error).__name__,
                )
                upload = BufferedInputFile(content, filename=message.media.file_name)
                try:
                    sent = await self._bot.send_document(document=upload, **kwargs)
                except TelegramAPIError as exc:
                    raise MessengerError("send_document", exc) from exc
        return DeliveryResult(
            platform=self.platform,
            external_chat_id=message.external_chat_id,
            external_message_id=str(sent.message_id),
            delivered_at=datetime.now(UTC),
        )

    async def delete_message(
        self, external_chat_id: str, external_message_id: str,
    ) -> None:
        try:
            await self._bot.delete_message(
                chat_id=int(external_chat_id), message_id=int(external_message_id),
            )
        except TelegramAPIError as exc:
            raise MessengerError("delete_message", exc) from exc
