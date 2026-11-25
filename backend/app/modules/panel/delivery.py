"""Shared panel recipient selection and attachment storage."""
import mimetypes
import re
import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.infrastructure.storage.media import ATTACHMENT_SIZE_ERROR, MAX_ATTACHMENT_BYTES, MEDIA_DIR, safe_media_type
from app.models import Conversation, User


def panel_sender_and_recipients(db: Session, principal: dict, conversation: Conversation):
    """Определить отправителя и адресатов для сообщения."""
    student = conversation.student
    teacher = conversation.teacher
    if principal["role"] == "teacher":
        sender = teacher
        recipients = [(student, "student")]
    elif principal["role"] == "student":
        sender = student
        recipients = [(teacher, "teacher")]
    else:
        sender = db.scalar(select(User).where(User.role == "admin").order_by(User.id).limit(1))
        if not sender:
            sender = User(full_name="Администратор", role="admin")
            db.add(sender)
            db.flush()
        recipients = [(student, "student"), (teacher, "teacher")]
    if not sender:
        raise HTTPException(status_code=401, detail="Учётная запись недоступна")
    return sender, recipients, student, teacher


def store_panel_attachment(file: UploadFile, conversation_id: int, *, personal: bool = False):
    """Проверить и сохранить вложение."""
    if file.size is not None and file.size > MAX_ATTACHMENT_BYTES:
        raise HTTPException(status_code=413, detail=ATTACHMENT_SIZE_ERROR)
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
                if target.tell() + len(chunk) > MAX_ATTACHMENT_BYTES:
                    raise HTTPException(status_code=413, detail=ATTACHMENT_SIZE_ERROR)
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
