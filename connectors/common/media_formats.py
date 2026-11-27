"""Portable attachment routing. Preserve original bytes; never claim an unsupported native format."""
from pathlib import PurePath

MEDIA_LABELS = {"voice": "Голосовое сообщение", "video_note": "Видеокружок",
                "sticker": "Стикер", "animation": "Анимация", "location": "Геолокация",
                "contact": "Контакт", "poll": "Опрос", "unsupported": "Вложение не поддерживается"}


def mime_and_suffix(media):
    return ((media.get("mime_type") or "").split(";", 1)[0].lower(),
            PurePath(media.get("file_name") or "").suffix.lower())


def max_inbound_kind(kind, mime, filename):
    mime, suffix = mime_and_suffix({"mime_type": mime, "file_name": filename})
    if kind == "image" and (mime == "image/gif" or suffix == ".gif"):
        return "animation"
    if kind == "audio" and (mime in {"audio/ogg", "audio/opus"} or suffix in {".ogg", ".opus"}):
        return "voice"
    if kind == "file" and (mime == "image/gif" or suffix == ".gif"):
        return "animation"
    return {"image": "photo", "video": "video", "audio": "audio",
            "file": "document", "sticker": "sticker"}.get(kind, kind)


def max_upload_kind(kind, media):
    mime, suffix = mime_and_suffix(media)
    if kind in {"photo", "sticker", "animation"}:
        if mime in {"image/jpeg", "image/png", "image/gif", "image/tiff", "image/bmp", "image/heic"} or (
                not mime or mime == "application/octet-stream") and suffix in {".jpg", ".jpeg", ".png", ".gif", ".tiff", ".bmp", ".heic"}:
            return "image"
        if kind == "animation" and (mime.startswith("video/") or suffix in {".mp4", ".webm"}):
            return "video"
        return "file"
    if kind in {"video", "video_note"}:
        return "video" if mime.startswith("video/") or suffix in {".mp4", ".mov", ".webm", ".mkv"} else "file"
    if kind in {"voice", "audio"}:
        # MAX documents MP3/M4A; OGG/Opus can always be delivered as a file.
        return "audio" if mime in {"audio/mpeg", "audio/mp3", "audio/mp4", "audio/aac", "audio/x-m4a"} or suffix in {".mp3", ".m4a", ".aac"} else "file"
    return "file"


def telegram_upload_kind(kind, media):
    mime, suffix = mime_and_suffix(media)
    if kind == "sticker":
        return "photo" if mime in {"image/jpeg", "image/png"} else "document"
    if kind == "video_note":
        return "video" if mime == "video/mp4" or suffix == ".mp4" else "document"
    if kind == "animation":
        return "animation" if mime in {"image/gif", "video/mp4"} or suffix in {".gif", ".mp4"} else "document"
    if kind == "voice":
        return "voice" if mime in {"audio/ogg", "audio/opus", "audio/mpeg", "audio/mp4"} or suffix in {".ogg", ".opus", ".mp3", ".m4a"} else "document"
    if kind == "audio" and mime not in {"audio/mpeg", "audio/mp3", "audio/mp4", ""} and suffix not in {".mp3", ".m4a"}:
        return "document"
    return kind


def delivery_text(job):
    kind = job.get("kind", "text")
    text = job.get("text") or ""
    if kind in MEDIA_LABELS:
        label = MEDIA_LABELS[kind]
        if kind in {"voice", "video_note", "sticker", "animation"} and not job.get("media"):
            label += " — файл недоступен"
        return text + "\n[" + label + "]"
    if not job.get("media") and kind != "text":
        return text + "\n[Вложение недоступно: " + kind + "]"
    return text
