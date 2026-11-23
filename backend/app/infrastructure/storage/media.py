"""Безопасное хранение медиафайлов."""

import contextlib
import hashlib
import json
import logging
from pathlib import Path

from fastapi import Request, Response
from fastapi.responses import FileResponse

from app.core.config import ROOT_DIR

logger = logging.getLogger(__name__)
MEDIA_DIR = ROOT_DIR / "data" / "media"

MAX_ATTACHMENT_BYTES = 1024 ** 3
ATTACHMENT_SIZE_ERROR = "Максимальный размер вложения — 1024 МиБ"

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
        relative = metadata.get("media", {}).get("local_path")
        if not relative:
            return
        root = MEDIA_DIR.resolve()
        target = (root / relative).resolve()
        if root not in target.parents:
            logger.warning("Skipping unsafe media path during cleanup")
            return
        target.unlink(missing_ok=True)
        with contextlib.suppress(OSError):
            target.parent.rmdir()
    except Exception:
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
