"""Shared Telegram message, account and conversation helpers."""

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Optional

from aiogram.types import Message as TgMessage
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .models import Assignment, ConnectionCode, Conversation, Message, User


EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
USERNAME_RE = re.compile(r"(?<!\w)@[A-Za-z][A-Za-z0-9_]{4,}")
TG_LINK_RE = re.compile(r"(?:https?://)?(?:t\.me|telegram\.me)/[A-Za-z0-9_]+", re.I)
PHONE_RE = re.compile(r"(?<!\w)\+?\d[\d\s().-]{6,}\d(?!\w)")


def text_contains_contact_data(body: str) -> bool:
    if EMAIL_RE.search(body) or USERNAME_RE.search(body) or TG_LINK_RE.search(body):
        return True
    for match in PHONE_RE.findall(body):
        if sum(char.isdigit() for char in match) >= 8:
            return True
    return False


def contact_would_be_exposed(message: TgMessage) -> bool:
    return bool(message.contact) or text_contains_contact_data(message.text or message.caption or "")


def message_metadata(message: TgMessage) -> dict:
    result = {}
    media_fields = ("photo", "document", "audio", "video", "voice", "video_note", "sticker", "animation")
    for field in media_fields:
        item = getattr(message, field, None)
        if not item:
            continue
        if isinstance(item, list):
            item = item[-1]
        result[field] = {
            "file_id": getattr(item, "file_id", None),
            "file_unique_id": getattr(item, "file_unique_id", None),
            "file_name": getattr(item, "file_name", None),
            "mime_type": getattr(item, "mime_type", None),
        }
        break
    if message.location:
        result["location"] = {"latitude": message.location.latitude, "longitude": message.location.longitude}
    if message.poll:
        result["poll"] = {"question": message.poll.question, "options": [option.text for option in message.poll.options]}
    if message.contact:
        result["contact_hidden"] = True
    return result


def persist_message(
    db: Session,
    conversation_id: int,
    sender: User,
    message: TgMessage,
    status: str,
    safe_text: Optional[str] = None,
) -> Message:
    body = safe_text if safe_text is not None else (message.text or message.caption or "")
    content_type = message.content_type.value if hasattr(message.content_type, "value") else str(message.content_type)
    metadata = message_metadata(message)
    if sender.role == "student":
        metadata["teacher_read_at"] = None
    row = Message(
        conversation_id=conversation_id,
        sender_id=sender.id,
        sender_role=sender.role,
        content_type=content_type,
        text=body[:12000],
        metadata_json=json.dumps(metadata, ensure_ascii=False),
        delivery_status=status,
        source_message_id=message.message_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


CONNECTION_CODE_RE = re.compile(r"^[A-HJ-NP-Z2-9]{8}$")


def claim_connection_code(
    db: Session,
    raw_code: str,
    telegram_id: int,
) -> tuple[Optional[User], str]:
    normalized = re.sub(r"[\s-]", "", raw_code).upper()
    if not CONNECTION_CODE_RE.fullmatch(normalized):
        return None, "invalid_format"

    code_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    connection_code = db.scalar(
        select(ConnectionCode).where(ConnectionCode.code_hash == code_hash)
    )
    if not connection_code:
        return None, "invalid"
    if connection_code.used_at is not None:
        return None, "used"

    now = datetime.now(timezone.utc)
    expires_at = connection_code.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= now:
        connection_code.used_at = now
        db.commit()
        return None, "expired"

    user = db.get(User, connection_code.user_id)
    if not user or not user.active or user.role not in {"teacher", "student"}:
        connection_code.used_at = now
        db.commit()
        return None, "inactive"

    existing_user = db.scalar(
        select(User).where(User.telegram_id == telegram_id)
    )
    if existing_user and existing_user.id != user.id:
        return None, "telegram_already_linked"
    if user.telegram_id and user.telegram_id != telegram_id:
        return None, "account_already_linked"

    # Atomically mark the code as used and bind the Telegram ID in one transaction.
    result = db.execute(
        update(ConnectionCode)
        .where(
            ConnectionCode.id == connection_code.id,
            ConnectionCode.used_at.is_(None),
        )
        .values(used_at=now)
    )
    if result.rowcount != 1:
        db.rollback()
        return None, "used"

    user.telegram_id = telegram_id
    try:
        db.commit()
        db.refresh(user)
    except IntegrityError:
        db.rollback()
        return None, "telegram_already_linked"
    return user, "ok"


def get_linked_user(db: Session, telegram_id: int) -> Optional[User]:
    return db.scalar(select(User).where(User.telegram_id == telegram_id, User.active.is_(True)))


def current_student_conversation(db: Session, student_id: int) -> Optional[Conversation]:
    assignment = db.scalar(
        select(Assignment).where(Assignment.student_id == student_id, Assignment.active.is_(True))
        .order_by(Assignment.created_at.desc())
    )
    if not assignment or not assignment.teacher.active:
        return None
    return assignment.conversation
