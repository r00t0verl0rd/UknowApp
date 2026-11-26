"""Validation and local storage of uploaded attachments."""
import mimetypes
import re
import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile

from app.infrastructure.storage.media import (
    MEDIA_DIR,
    attachment_size_error,
    panel_attachment_limit,
    safe_media_type,
)


def store_panel_attachment(file: UploadFile, conversation_id: int, *, personal: bool = False):
    """Проверить и сохранить вложение."""
    limit = panel_attachment_limit()
    if file.size is not None and file.size > limit:
        raise HTTPException(status_code=413, detail=attachment_size_error(limit))
    original_name = (file.filename or "attachment").replace("\\", "/").rsplit("/", 1)[-1]
    original_name = "".join(
        char for char in original_name
        if ord(char) >= 32 and char not in "\r\n"
    )[:180].strip() or "attachment"
    suffix = re.sub(r"[^A-Za-z0-9.]", "", Path(original_name).suffix)[:12]
    if not suffix:
        suffix = mimetypes.guess_extension(file.content_type or "") or ".bin"

    relative = (Path('personal') if personal else Path()) / str(conversation_id) / (uuid.uuid4().hex + suffix)
    target_path = (MEDIA_DIR / relative).resolve()
    root = MEDIA_DIR.resolve()
    if root not in target_path.parents:
        raise HTTPException(status_code=400, detail="Недопустимое имя файла")
    target_path.parent.mkdir(parents=True, exist_ok=True)
    def copy_upload():
        with target_path.open("xb") as target:
            while chunk := file.file.read(1024 * 1024):
                if target.tell() + len(chunk) > limit:
                    raise HTTPException(status_code=413, detail=attachment_size_error(limit))
                target.write(chunk)
            return target.tell()

    try:
        size = copy_upload()
        if not size:
            raise HTTPException(status_code=400, detail="Файл пустой")
    except BaseException:
        target_path.unlink(missing_ok=True)
        raise

    reported_mime_type = file.content_type or mimetypes.guess_type(original_name)[0]
    mime_type = safe_media_type(reported_mime_type)
    if mime_type == "image/gif":
        kind = "animation"
    elif mime_type.startswith("image/"):
        kind = "photo"
    elif mime_type.startswith("video/"):
        kind = "video"
    elif mime_type.startswith("audio/"):
        kind = "voice" if mime_type in {"audio/ogg", "audio/opus"} else "audio"
    else:
        kind = "document"
    return size, original_name, relative, mime_type, kind
