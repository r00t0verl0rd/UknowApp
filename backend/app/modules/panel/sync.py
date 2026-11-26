"""Синхронизация прочтения и состояния диалогов."""

import logging

from fastapi import (
    APIRouter,
    HTTPException,
)
from pydantic import BaseModel, Field, PositiveInt
from sqlalchemy import select
from sqlalchemy.orm import joinedload, load_only

from app.models import (
    Message,
    PersonalMessage,
)
from app.modules.conversations.service import (
    conversation_dicts,
)
from app.modules.dependencies import Db, PanelUser
from app.modules.messaging.history import sync_page
from app.modules.messaging.read_state import mark_conversation_read, mark_personal_read
from app.modules.messaging.service import (
    panel_message_dict,
    panel_message_status_dict,
    panel_visible_conversation,
)
from app.modules.personal_chat.operations import (
    personal_message_dict,
    personal_message_status_dict,
    personal_summaries,
)
from app.modules.personal_chat.service import (
    personal_conversation,
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
    conversation = panel_visible_conversation(db, principal, conversation_id)
    query = select(Message).options(joinedload(Message.sender)).where(
        Message.conversation_id == conversation.id, Message.id > after_id,
    )
    new_rows, has_more = sync_page(db, query, Message, after_id)
    if payload.get("mark_read") is not False and principal["role"] != "admin":
        mark_conversation_read(db, conversation, principal, after_id, [row.id for row in new_rows])
    updated_rows = []
    for start in range(0, len(known_ids), 500):
        batch_ids = known_ids[start:start + 500]
        updated_rows.extend(db.scalars(
            select(Message)
            .options(load_only(Message.id, Message.sender_role, Message.delivery_status, Message.metadata_json, Message.teacher_read_at, Message.student_read_at, Message.admin_read_at))
            .where(
                Message.conversation_id == conversation.id,
                Message.id.in_(batch_ids),
            )
            .order_by(Message.created_at, Message.id),
        ).all())

    def serialize(rows):
        return [
            panel_message_dict(
                row,
                expose_internal_metadata=(principal["role"] == "admin"),
                principal=principal,
            )
            for row in rows
        ]

    def serialize_statuses(rows):
        return [panel_message_status_dict(row, principal) for row in rows]

    summary = conversation_dicts(
        db, [conversation], include_messenger_accounts=(principal["role"] == "admin"),
        viewer_role=principal["role"],
    )[0]
    return {
        "messages": serialize(new_rows),
        "has_more": has_more,
        "deleted_message_ids": sorted(set(known_ids).difference(row.id for row in updated_rows)),
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
    item = personal_conversation(db, principal, conversation_id)
    query = select(PersonalMessage).options(joinedload(PersonalMessage.sender)).where(
        PersonalMessage.conversation_id == item.id, PersonalMessage.id > after_id,
    )
    new_rows, has_more = sync_page(db, query, PersonalMessage, after_id)
    if payload.get("mark_read") is not False:
        mark_personal_read(db, item, principal, after_id, [row.id for row in new_rows])
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
        "has_more": has_more,
        "deleted_message_ids": sorted(set(known_ids).difference(row.id for row in updated_rows)),
        "updated_messages": [personal_message_status_dict(row) for row in updated_rows],
        "summary": personal_summaries(db, [item], principal["role"])[0],
    }


class ReadReceipt(BaseModel):
    message_ids: list[PositiveInt] = Field(min_length=1, max_length=500)


@router.post("/panel/conversations/{conversation_id}/read")
def read_conversation(conversation_id: int, payload: ReadReceipt, principal: PanelUser, db: Db):
    conversation = panel_visible_conversation(db, principal, conversation_id)
    mark_conversation_read(db, conversation, principal, 0, payload.message_ids)
    return conversation_dicts(
        db, [conversation], include_messenger_accounts=(principal["role"] == "admin"),
        viewer_role=principal["role"],
    )[0]


@router.post("/panel/personal-conversations/{conversation_id}/read")
def read_personal_conversation(conversation_id: int, payload: ReadReceipt, principal: PanelUser, db: Db):
    item = personal_conversation(db, principal, conversation_id)
    mark_personal_read(db, item, principal, 0, payload.message_ids)
    return personal_summaries(db, [item], principal["role"])[0]
