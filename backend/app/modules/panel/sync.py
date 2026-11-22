"""Синхронизация прочтения и состояния диалогов."""

import json
import logging
from datetime import UTC, datetime

from fastapi import (
    APIRouter,
    HTTPException,
)
from sqlalchemy import func, select, update
from sqlalchemy.orm import load_only, selectinload

from app.models import (
    Message,
    PersonalMessage,
)
from app.modules.conversations.service import (
    conversation_dicts,
    publish_conversation_update,
)
from app.modules.dependencies import Db, PanelUser
from app.modules.messaging.service import (
    _panel_message_dict,
    _panel_message_status_dict,
    _panel_visible_conversation,
)
from app.modules.personal_chat.service import (
    _personal_conversation,
    publish_personal_update,
)

from .personal import (
    personal_message_dict,
    personal_message_status_dict,
    personal_summaries,
)

logger = logging.getLogger(__name__)
router = APIRouter()


def _sync_request_fields(payload: dict) -> tuple[int, list[int]]:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="Некорректный запрос синхронизации")
    after_id = payload.get("after_id", 0)
    known_ids = payload.get("known_message_ids", [])
    if isinstance(after_id, bool) or not isinstance(after_id, int) or after_id < 0:
        raise HTTPException(status_code=422, detail="Некорректный курсор сообщений")
    if not isinstance(known_ids, list) or len(known_ids) > 5000:
        raise HTTPException(status_code=422, detail="Некорректный список сообщений")
    normalized = []
    for value in known_ids:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise HTTPException(status_code=422, detail="Некорректный идентификатор сообщения")
        normalized.append(value)
    return after_id, list(dict.fromkeys(normalized))


@router.post("/panel/conversations/{conversation_id}/sync")
def sync_conversation_state(
    conversation_id: int,
    payload: dict,
    principal: PanelUser,
    db: Db,
):
    """Обновить изменения сообщений без полной загрузки истории."""
    after_id, known_ids = _sync_request_fields(payload)
    conversation = _panel_visible_conversation(db, principal, conversation_id)
    if principal["role"] in {"teacher", "student"}:
        read_key = "teacher_read_at" if principal["role"] == "teacher" else "student_read_at"
        sender_roles = ("student", "admin") if principal["role"] == "teacher" else ("teacher", "admin")
        unread = db.scalars(
            select(Message).where(
                Message.conversation_id == conversation.id,
                Message.sender_role.in_(sender_roles),
                func.json_extract(Message.metadata_json, "$." + read_key).is_(None),
                Message.id > after_id,
            ),
        ).all()
        if unread:
            read_at = datetime.now(UTC).isoformat()
            for row in unread:
                metadata = json.loads(row.metadata_json or "{}")
                metadata[read_key] = read_at
                row.metadata_json = json.dumps(metadata, ensure_ascii=False)
            db.commit()
            publish_conversation_update(
                db, conversation, action="read", actor_role=principal["role"],
                message_ids=[row.id for row in unread], read_at=read_at,
            )

    new_rows = db.scalars(
        select(Message)
        .where(Message.conversation_id == conversation.id, Message.id > after_id)
        .order_by(Message.created_at, Message.id),
    ).all()
    updated_rows = []
    for start in range(0, len(known_ids), 500):
        batch_ids = known_ids[start:start + 500]
        updated_rows.extend(db.scalars(
            select(Message)
            .options(load_only(Message.id, Message.sender_role, Message.delivery_status, Message.metadata_json))
            .where(
                Message.conversation_id == conversation.id,
                Message.id.in_(batch_ids),
            )
            .order_by(Message.created_at, Message.id),
        ).all())

    def serialize(rows):
        return [
            _panel_message_dict(
                row,
                expose_internal_metadata=(principal["role"] == "admin"),
                principal=principal,
            )
            for row in rows
        ]

    def serialize_statuses(rows):
        return [_panel_message_status_dict(row, principal) for row in rows]

    summary = conversation_dicts(
        db, [conversation], include_telegram_ids=(principal["role"] == "admin"),
        viewer_role=principal["role"],
    )[0]
    return {
        "messages": serialize(new_rows),
        "updated_messages": serialize_statuses(updated_rows),
        "summary": summary,
    }


@router.post("/panel/personal-conversations/{conversation_id}/sync")
def sync_personal_conversation_state(
    conversation_id: int,
    payload: dict,
    principal: PanelUser,
    db: Db,
):
    """Обновить личные сообщения и отметки прочтения."""
    after_id, known_ids = _sync_request_fields(payload)
    item = _personal_conversation(db, principal, conversation_id)
    read_column = PersonalMessage.admin_read_at if principal["role"] == "admin" else PersonalMessage.participant_read_at
    read_ids = db.scalars(
        select(PersonalMessage.id).where(
            PersonalMessage.conversation_id == item.id,
            PersonalMessage.sender_role != principal["role"],
            read_column.is_(None),
            PersonalMessage.id > after_id,
        ),
    ).all()
    if read_ids:
        read_at = datetime.now(UTC)
        db.execute(
            update(PersonalMessage)
            .where(PersonalMessage.id.in_(read_ids))
            .values({read_column.key: read_at}),
        )
        db.commit()
        publish_personal_update(
            db, item, action="read", actor_role=principal["role"],
            message_ids=read_ids, read_at=read_at.isoformat(),
        )

    new_rows = db.scalars(
        select(PersonalMessage)
        .options(selectinload(PersonalMessage.sender))
        .where(PersonalMessage.conversation_id == item.id, PersonalMessage.id > after_id)
        .order_by(PersonalMessage.created_at, PersonalMessage.id),
    ).all()
    updated_rows = []
    for start in range(0, len(known_ids), 500):
        batch_ids = known_ids[start:start + 500]
        updated_rows.extend(db.scalars(
            select(PersonalMessage)
            .options(load_only(PersonalMessage.id, PersonalMessage.sender_role, PersonalMessage.admin_read_at, PersonalMessage.participant_read_at))
            .where(
                PersonalMessage.conversation_id == item.id,
                PersonalMessage.id.in_(batch_ids),
            )
            .order_by(PersonalMessage.created_at, PersonalMessage.id),
        ).all())
    return {
        "messages": [personal_message_dict(row, principal) for row in new_rows],
        "updated_messages": [personal_message_status_dict(row) for row in updated_rows],
        "summary": personal_summaries(db, [item], principal["role"])[0],
    }
