"""Отметки прочтения: помечают входящие сообщения прочитанными и публикуют событие."""

from datetime import UTC, datetime

from sqlalchemy import select, update

from app.infrastructure.storage.message_metadata import (
    metadata_with_field,
)
from app.models import Message, PersonalMessage
from app.modules.conversations.service import publish_conversation_update, _unread_condition, read_cursor
from app.modules.personal_chat.service import publish_personal_update


def mark_conversation_read(db, conversation, principal, after_id: int, visible_ids=None) -> None:
    """Учитель и ученик помечают прочитанными новые сообщения собеседников; администратор ничего не помечает."""
    role = principal["role"]
    if role not in {"teacher", "student"} or (visible_ids is not None and not visible_ids):
        return
    read_key = "teacher_read_at" if role == "teacher" else "student_read_at"
    filters = (
        Message.conversation_id == conversation.id,
        _unread_condition(db, role),
        Message.id > read_cursor(conversation.id, role),
        Message.id > after_id,
        *([Message.id.in_(visible_ids)] if visible_ids is not None else []),
    )
    # Do not take SQLite's writer lock just to open an already-read chat.
    if db.scalar(select(Message.id).where(*filters).limit(1)) is None:
        return
    read_at = datetime.now(UTC).isoformat()
    ids = db.scalars(update(Message).where(*filters)
      .values(metadata_json=metadata_with_field(db, Message.metadata_json, read_key, read_at))
      .returning(Message.id), execution_options={"synchronize_session": "fetch"}).all()
    if not ids:
        db.rollback()
        return
    db.commit()
    publish_conversation_update(
        db, conversation, action="read", actor_role=role,
        message_ids=sorted(ids), read_at=read_at,
    )


def mark_personal_read(db, item, principal, after_id: int, visible_ids=None) -> None:
    """Помечает прочитанными новые сообщения собеседника в личном диалоге."""
    role = principal["role"]
    if visible_ids is not None and not visible_ids:
        return
    read_column = PersonalMessage.admin_read_at if role == "admin" else PersonalMessage.participant_read_at
    read_ids = db.scalars(
        select(PersonalMessage.id).where(
            PersonalMessage.conversation_id == item.id,
            PersonalMessage.sender_role != role,
            read_column.is_(None),
            PersonalMessage.id > after_id,
            *([PersonalMessage.id.in_(visible_ids)] if visible_ids is not None else []),
        ),
    ).all()
    if not read_ids:
        return
    read_at = datetime.now(UTC)
    db.execute(
        update(PersonalMessage)
        .where(PersonalMessage.id.in_(read_ids))
        .values({read_column.key: read_at}),
    )
    db.commit()
    publish_personal_update(
        db, item, action="read", actor_role=role,
        message_ids=read_ids, read_at=read_at.isoformat(),
    )
