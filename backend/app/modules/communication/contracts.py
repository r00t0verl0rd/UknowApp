"""Messenger-independent communication contracts.

These types describe the boundary between UknowApp and external messaging
platforms. They deliberately contain no aiogram, MAX, or WhatsApp types.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Mapping, Protocol, Sequence


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
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True, slots=True)
class InboundMedia:
    """A media reference owned by the receiving platform adapter."""

    file_name: str | None = None
    mime_type: str | None = None
    file_size: int | None = None
    provider_file_id: str | None = None


@dataclass(frozen=True, slots=True)
class InboundMessage:
    """A normalized user message received from any supported messenger."""

    platform: MessengerPlatform
    event_id: str
    external_user_id: str
    external_chat_id: str
    external_message_id: str
    content_type: MessageKind
    text: str = ""
    caption: str = ""
    media: InboundMedia | None = None
    occurred_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class OutboundMedia:
    """A reference to media already stored by UknowApp."""

    storage_key: str
    file_name: str
    mime_type: str | None = None


@dataclass(frozen=True, slots=True)
class OutboundMessage:
    """A platform-neutral request to deliver a message to an external chat."""

    platform: MessengerPlatform
    external_chat_id: str
    content_type: MessageKind
    external_thread_id: str | None = None
    text: str = ""
    media: OutboundMedia | None = None
    reply_to_external_message_id: str | None = None
    idempotency_key: str | None = None


@dataclass(frozen=True, slots=True)
class DeliveryResult:
    """The external identifiers and timestamp returned after a delivery."""

    platform: MessengerPlatform
    external_chat_id: str
    external_message_id: str
    delivered_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class MessengerCapabilities:
    """Features an adapter can expose without promising platform parity."""

    text: bool = True
    attachments: bool = False
    edit_messages: bool = False
    delete_messages: bool = False
    interactive_messages: bool = False
    group_chats: bool = False
    threaded_chats: bool = False


class MessengerAdapter(Protocol):
    """Minimal contract implemented by each concrete messenger adapter."""

    @property
    def platform(self) -> MessengerPlatform:
        ...

    @property
    def capabilities(self) -> MessengerCapabilities:
        ...

    def normalize_event(
        self, payload: Mapping[str, object]
    ) -> Sequence[InboundMessage]:
        """Convert a provider event into zero or more normalized messages."""
        ...

    async def send(self, message: OutboundMessage) -> DeliveryResult:
        """Deliver a normalized message and return its provider identifiers."""
        ...
