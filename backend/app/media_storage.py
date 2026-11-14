import json
import logging
import mimetypes
import uuid
from pathlib import Path
from typing import Optional

from aiogram import Bot
from aiogram.types import Message as TgMessage

from .config import ROOT_DIR
from .models import Message

logger = logging.getLogger(__name__)
MEDIA_DIR = ROOT_DIR / "data" / "media"

SAFE_MEDIA_TYPES = {
    "image/jpeg", "image/png", "image/gif", "image/webp", "image/bmp",
    "audio/mpeg", "audio/mp3", "audio/ogg", "audio/opus", "audio/wav",
    "audio/x-wav", "audio/mp4", "audio/aac", "audio/flac", "audio/webm",
    "video/mp4", "video/webm", "video/ogg", "video/quicktime",
    "application/pdf",
    "text/plain", "text/csv",
    "application/zip", "application/x-zip-compressed",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-powerpoint",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}


def safe_media_type(value: Optional[str]) -> str:
    """Only return known browser-safe MIME types; unknown types are downloads."""
    normalized = (value or "").split(";", 1)[0].strip().lower()
    return normalized if normalized in SAFE_MEDIA_TYPES else "application/octet-stream"


def media_content_disposition(kind: Optional[str], value: Optional[str]) -> str:
    mime_type = safe_media_type(value)
    if kind == "photo" and mime_type.startswith("image/") and mime_type != "image/svg+xml":
        return "inline"
    if kind in {"voice", "audio"} and mime_type.startswith("audio/"):
        return "inline"
    if kind in {"video", "video_note", "animation"} and mime_type.startswith("video/"):
        return "inline"
    return "attachment"


def _media_item(message: TgMessage):
    for field in ("photo", "document", "audio", "video", "voice", "video_note", "sticker", "animation"):
        item = getattr(message, field, None)
        if item:
            return field, item[-1] if isinstance(item, list) else item
    return None, None


async def archive_telegram_media(bot: Bot, message: TgMessage, row: Message) -> None:
    """Download supported Telegram attachments into persistent app storage."""
    field, item = _media_item(message)
    if not item:
        return
    metadata = json.loads(row.metadata_json or "{}")
    media = {
        "kind": field,
        "file_id": item.file_id,
        "file_unique_id": getattr(item, "file_unique_id", None),
        "file_name": getattr(item, "file_name", None),
        "mime_type": safe_media_type(
            getattr(item, "mime_type", None)
            or {
                "photo": "image/jpeg",
                "video": "video/mp4",
                "video_note": "video/mp4",
                "voice": "audio/ogg",
            }.get(field)
        ),
        "file_size": getattr(item, "file_size", None),
        "archive_status": "pending",
    }
    metadata["media"] = media
    try:
        # Telegram's hosted Bot API currently limits getFile downloads to 20 MB.
        if getattr(item, "file_size", 0) and item.file_size > 20 * 1024 * 1024:
            media["archive_status"] = "too_large_for_telegram_download"
        else:
            suffix = Path(getattr(item, "file_name", None) or "").suffix.lower()
            if not suffix:
                suffix = mimetypes.guess_extension(getattr(item, "mime_type", None) or "") or {
                    "voice": ".ogg", "video_note": ".mp4", "video": ".mp4",
                    "photo": ".jpg", "sticker": ".webp", "animation": ".mp4",
                }.get(field, ".bin")
            relative = Path(str(row.conversation_id)) / (uuid.uuid4().hex + suffix[:12])
            target = MEDIA_DIR / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            await bot.download(item.file_id, destination=target)
            media["local_path"] = relative.as_posix()
            media["archive_status"] = "stored"
    except Exception:
        logger.exception("Could not archive Telegram media for message_id=%s", row.id)
        media["archive_status"] = "download_failed"
    row.metadata_json = json.dumps(metadata, ensure_ascii=False)


def delete_message_media(metadata_json: Optional[str]) -> None:
    try:
        metadata = json.loads(metadata_json or "{}")
        relative = metadata.get("media", {}).get("local_path")
        if not relative:
            return
        root = MEDIA_DIR.resolve()
        target = (root / relative).resolve()
        if root not in target.parents:
            logger.warning("Skipping unsafe media path during cleanup")
            return
        target.unlink(missing_ok=True)
        try:
            target.parent.rmdir()
        except OSError:
            pass
    except Exception:
        logger.exception("Could not delete archived message media")
