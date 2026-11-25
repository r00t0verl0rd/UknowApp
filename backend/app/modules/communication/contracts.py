"""Общие типы и интерфейсы мессенджеров."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class MessengerError(Exception):
    """Ошибка обращения к внешнему мессенджеру."""

    def __init__(self, operation: str, cause: Exception) -> None:
        self.operation = operation
        self.provider_error_type = type(cause).__name__
        super().__init__(f"{operation} failed ({self.provider_error_type})")


class MessengerPlatform(StrEnum):
    TELEGRAM = "telegram"
    MAX = "max"
    WHATSAPP = "whatsapp"


class MessageKind(StrEnum):
    TEXT = "text"
    PHOTO = "photo"
    VIDEO = "video"
    AUDIO = "audio"
    VOICE = "voice"
    DOCUMENT = "document"
    ANIMATION = "animation"
    STICKER = "sticker"
    LOCATION = "location"
    CONTACT = "contact"
    VIDEO_NOTE = "video_note"
    POLL = "poll"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True, slots=True)
class InboundMedia:
    """Ссылка на медиафайл мессенджера."""

    file_name: str | None = None
    mime_type: str | None = None
    file_size: int | None = None
    provider_file_id: str | None = None
    provider_unique_file_id: str | None = None
    is_video: bool = False
    is_animated: bool = False


@dataclass(frozen=True, slots=True)
class InboundLocation:
    latitude: float
    longitude: float


@dataclass(frozen=True, slots=True)
class InboundPoll:
    question: str
    options: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class InboundMessage:
    """Сообщение в едином внутреннем формате."""

    platform: MessengerPlatform
    event_id: str
    external_user_id: str | None
    external_chat_id: str
    external_message_id: str
    content_type: MessageKind
    text: str = ""
    caption: str = ""
    media: InboundMedia | None = None
    occurred_at: datetime | None = None
    external_thread_id: str | None = None
    sender_username: str | None = None
    sender_chat_id: str | None = None
    chat_type: str = "private"
    chat_is_forum: bool = False
    chat_title: str | None = None
    location: InboundLocation | None = None
    poll: InboundPoll | None = None
    contact_present: bool = False


@dataclass(frozen=True, slots=True)
class OutboundMedia:
    """Ссылка на сохранённый файл UknowApp."""

    storage_key: str
    file_name: str
    mime_type: str | None = None


@dataclass(frozen=True, slots=True)
class OutboundMessage:
    """Запрос отправки сообщения во внешний чат."""

    platform: MessengerPlatform
    external_chat_id: str
    content_type: MessageKind
    external_thread_id: str | None = None
    text: str = ""
    media: OutboundMedia | None = None
    reply_to_external_message_id: str | None = None
    idempotency_key: str | None = None
