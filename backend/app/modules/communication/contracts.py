"""Общие типы и интерфейсы мессенджеров."""

from enum import StrEnum


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
