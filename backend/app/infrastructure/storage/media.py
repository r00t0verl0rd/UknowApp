"""Безопасное хранение медиафайлов."""

import contextlib
import hashlib
import json
import logging
import os
from pathlib import Path

from fastapi import Request, Response
from fastapi.responses import FileResponse

from app.core.config import ROOT_DIR

logger = logging.getLogger(__name__)
MEDIA_DIR = ROOT_DIR / "data" / "media"

MAX_ATTACHMENT_BYTES = 1024 ** 3
ATTACHMENT_SIZE_ERROR = "Максимальный размер вложения — 1024 МиБ"

TELEGRAM_ATTACHMENT_LIMITS = {"cloud": 20 * 1024 ** 2, "local": 888 * 1024 ** 2}
MAX_MESSENGER_ATTACHMENT_BYTES = 888 * 1024 ** 2


def provider_attachment_limit(platform: str) -> int:
    if platform == "max":
        return MAX_MESSENGER_ATTACHMENT_BYTES
    if platform != "telegram":
        return MAX_ATTACHMENT_BYTES
    mode = os.getenv("TELEGRAM_API_MODE", "cloud")
    if mode not in TELEGRAM_ATTACHMENT_LIMITS:
        raise ValueError("invalid Telegram API mode")
    return TELEGRAM_ATTACHMENT_LIMITS[mode]


def panel_attachment_limit() -> int:
    # Без ботов действует общий лимит веб-приложения.
    enabled = {item.strip() for item in os.getenv("BOTS_PLATFORMS", "").split(",")}
    return min((provider_attachment_limit(p) for p in enabled), default=MAX_ATTACHMENT_BYTES)


def attachment_size_error(limit: int) -> str:
    return f"Максимальный размер вложения — {limit // 1024 ** 2} МиБ"

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


def safe_media_type(value: str | None) -> str:
    """Неизвестные типы файлов отдавать на скачивание."""
    normalized = (value or "").split(";", 1)[0].strip().lower()
    return normalized if normalized in SAFE_MEDIA_TYPES else "application/octet-stream"


def media_content_disposition(kind: str | None, value: str | None) -> str:
    mime_type = safe_media_type(value)
    if kind in {"photo", "sticker"} and mime_type.startswith("image/") and mime_type != "image/svg+xml":
        return "inline"
    if kind == "animation" and mime_type == "image/gif":
        return "inline"
    if kind in {"voice", "audio"} and mime_type.startswith("audio/"):
        return "inline"
    if kind in {"video", "video_note", "animation", "video_sticker"} and mime_type.startswith("video/"):
        return "inline"
    return "attachment"


def delete_message_media(metadata_json: str | None) -> None:
    try:
        metadata = json.loads(metadata_json or "{}")
        media = metadata.get("media") if isinstance(metadata, dict) else None
        relative = media.get("local_path") if isinstance(media, dict) else None
        if not isinstance(relative, str) or not relative:
            return
        root = MEDIA_DIR.resolve()
        target = (root / relative).resolve()
        if root not in target.parents:
            logger.warning("Skipping unsafe media path during cleanup")
            return
        target.unlink(missing_ok=True)
        with contextlib.suppress(OSError):
            target.parent.rmdir()
    except (OSError, ValueError, RuntimeError):
    # RuntimeError также возникает при цикле символических ссылок.
        logger.exception("Could not delete archived message media")

def attachment_response(request: Request, path: Path, media: dict) -> Response:
    """Revalidate only after the caller has checked current chat access."""
    stat = path.stat()
    version = f"{path.name}:{stat.st_ino}:{stat.st_size}:{stat.st_mtime_ns}:{stat.st_ctime_ns}"
    etag = '"' + hashlib.sha256(version.encode()).hexdigest() + '"'
    headers = {"ETag": etag, "Cache-Control": "private, no-cache", "Vary": "Cookie",
               "X-Content-Type-Options": "nosniff", "Content-Security-Policy": "sandbox"}
    validators = request.headers.get("if-none-match", "").split(",")
    if any(value.strip().removeprefix("W/") in {etag, "*"} for value in validators):
        return Response(status_code=304, headers=headers)
    return FileResponse(path, stat_result=stat, headers=headers,
                        media_type=safe_media_type(media.get("mime_type")),
                        filename=media.get("file_name") or path.name,
                        content_disposition_type=media_content_disposition(media.get("kind"), media.get("mime_type")))
