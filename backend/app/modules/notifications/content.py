"""Короткие подписи для уведомлений о сообщениях."""

PUSH_TITLE = "Новое сообщение"

_MEDIA_LABELS = {
    "photo": "Фото",
    "voice": "Голосовое",
    "audio": "Аудио",
    "video": "Видео",
    "video_note": "Видеосообщение",
    "document": "Файл",
    "animation": "GIF",
    "sticker": "Стикер",
    "location": "Геолокация",
    "contact": "Контакт",
    "poll": "Опрос",
}


def _shorten(value: str | None, limit: int) -> str:
    text = " ".join((value or "").split())
    if len(text) <= limit:
        return text
    return text[:limit - 1].rstrip() + "…"


def push_body(
    sender_name: str,
    text: str | None,
    *,
    recipient_name: str | None = None,
    kind: str = "text",
) -> str:
    """Обычный пуш показывает отправителя, админский — обоих участников."""
    sender = _shorten(sender_name, 32) or "Участник"
    heading = sender
    if recipient_name:
        heading += " → " + (_shorten(recipient_name, 32) or "Участник")
    preview = " ".join((text or "").split())
    if kind != "text":
        label = _MEDIA_LABELS.get(kind, "Вложение")
        preview = f"{label}: {preview}" if preview else label
    preview = _shorten(preview or "Сообщение", min(85, max(12, 155 - len(heading) - 2)))
    return f"{heading}: {preview}"
