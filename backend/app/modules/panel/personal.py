"""Личные диалоги администратора с участниками."""

import logging
from datetime import UTC, datetime

from fastapi import (
    APIRouter,
    HTTPException,
)
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.models import (
    PersonalConversation,
    PersonalMessage,
    User,
)
from app.modules.dependencies import Db, PanelUser
from app.modules.notifications.service import schedule_push
from app.modules.personal_chat.service import (
    _personal_conversation,
    _personal_conversation_dict,
    publish_personal_update,
)
from app.request_validation import message_payload, personal_conversation_payload

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/panel/personal-conversations")
def personal_conversations(principal: PanelUser, db: Db):
    statement = select(PersonalConversation).options(
        selectinload(PersonalConversation.participant),
    ).order_by(PersonalConversation.created_at.desc(), PersonalConversation.id.desc())
    if principal["role"] != "admin":
        statement = statement.where(PersonalConversation.participant_id == principal["user_id"])
    items = db.scalars(statement).all()
    if not items:
        return []
    return personal_summaries(db, items, principal["role"])


def personal_summaries(db: Session, items: list[PersonalConversation], role: str) -> list[dict]:
    read_at = PersonalMessage.admin_read_at if role == "admin" else PersonalMessage.participant_read_at
    unread = func.count(PersonalMessage.id).filter(PersonalMessage.sender_role != role, read_at.is_(None))
    rows = db.execute(
        select(PersonalMessage.conversation_id, unread, func.max(PersonalMessage.created_at))
        .where(PersonalMessage.conversation_id.in_([item.id for item in items]))
        .group_by(PersonalMessage.conversation_id),
    )
    stats = {chat_id: (count, latest) for chat_id, count, latest in rows}
    return [_personal_conversation_dict(item, role, *stats.get(item.id, (0, None))) for item in items]


@router.post("/panel/personal-conversations", status_code=201)
def create_personal_conversation(payload: dict, principal: PanelUser, db: Db):
    payload = personal_conversation_payload(payload)
    if principal["role"] != "admin":
        raise HTTPException(status_code=403, detail="Создавать личные диалоги может только администратор")
    participant = db.get(User, payload["user_id"])
    if not participant or participant.role not in {"teacher", "student"}:
        raise HTTPException(status_code=404, detail="Участник не найден")
    item = db.scalar(select(PersonalConversation).where(PersonalConversation.participant_id == participant.id))
    if not item:
        item = PersonalConversation(participant_id=participant.id)
        db.add(item)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            item = db.scalar(select(PersonalConversation).where(PersonalConversation.participant_id == participant.id))
            if item is None:
                raise
        else:
            publish_personal_update(db, item)
            return _personal_conversation_dict(item, principal["role"])
    return personal_summaries(db, [item], principal["role"])[0]


@router.get("/panel/personal-conversations/{conversation_id}/summary")
def personal_conversation_summary(conversation_id: int, principal: PanelUser, db: Db):
    item = _personal_conversation(db, principal, conversation_id)
    return personal_summaries(db, [item], principal["role"])[0]


def personal_message_dict(row: PersonalMessage, principal: dict) -> dict:
    return {
        "id": row.id,
        "sender": row.sender.full_name if row.sender else "Администратор",
        "sender_role": row.sender_role,
        "can_delete": row.sender_role == principal["role"] and (
            principal["role"] == "admin" or row.sender_id == principal.get("user_id")
        ),
        "content_type": "text",
        "text": row.text,
        "metadata": {},
        "delivery_status": "delivered",
        "panel_read_at": (
            row.admin_read_at.isoformat() if row.sender_role != "admin"
            and row.admin_read_at else
            row.participant_read_at.isoformat() if row.sender_role == "admin"
            and row.participant_read_at else None
        ),
        "created_at": row.created_at.isoformat(),
    }


def personal_message_status_dict(row: PersonalMessage) -> dict:
    read_at = (
        row.admin_read_at if row.sender_role != "admin"
        else row.participant_read_at
    )
    return {"id": row.id, "panel_read_at": read_at.isoformat() if read_at else None}


@router.get("/panel/personal-conversations/{conversation_id}/messages")
def personal_messages(conversation_id: int, principal: PanelUser, db: Db, after_id: int = 0):
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
    rows = db.scalars(
        select(PersonalMessage)
        .options(selectinload(PersonalMessage.sender))
        .where(PersonalMessage.conversation_id == item.id, PersonalMessage.id > after_id)
        .order_by(PersonalMessage.created_at, PersonalMessage.id),
    ).all()
    return [personal_message_dict(row, principal) for row in rows]


@router.get("/panel/personal-messages/{message_id}")
def personal_message(message_id: int, principal: PanelUser, db: Db):
    row = db.get(PersonalMessage, message_id)
    if not row:
        raise HTTPException(status_code=404, detail="Сообщение не найдено")
    _personal_conversation(db, principal, row.conversation_id)
    return personal_message_dict(row, principal)


@router.post("/panel/personal-conversations/{conversation_id}/messages", status_code=201)
def send_personal_message(
    conversation_id: int,
    payload: dict,
    principal: PanelUser,
    db: Db,
):
    payload = message_payload(payload)
    item = _personal_conversation(db, principal, conversation_id)
    if principal["role"] not in {"admin", "teacher", "student"}:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    if principal["role"] == "admin":
        sender_id = None
    else:
        sender = db.get(User, principal["user_id"])
        if not sender or sender.id != item.participant_id:
            raise HTTPException(status_code=403, detail="Нет доступа к личному диалогу")
        sender_id = sender.id
    client_message_id = payload.get("client_message_id")
    if client_message_id:
        existing = db.scalar(
            select(PersonalMessage).where(
                PersonalMessage.conversation_id == item.id,
                PersonalMessage.sender_role == principal["role"],
                PersonalMessage.client_message_id == client_message_id,
            ).limit(1),
        )
        if existing:
            return personal_message_dict(existing, principal)

    row = PersonalMessage(
        conversation_id=item.id,
        sender_id=sender_id,
        sender_role=principal["role"],
        text=payload["text"].strip(),
        client_message_id=client_message_id,
    )
    if not row.text:
        raise HTTPException(status_code=400, detail="Введите сообщение")
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        if client_message_id:
            existing = db.scalar(
                select(PersonalMessage).where(
                    PersonalMessage.conversation_id == item.id,
                    PersonalMessage.sender_role == principal["role"],
                    PersonalMessage.client_message_id == client_message_id,
                ).limit(1),
            )
            if existing:
                return personal_message_dict(existing, principal)
        raise
    db.refresh(row)
    schedule_push(
        db,
        [item.participant_id] if principal["role"] == "admin" else [],
        "Новое личное сообщение",
        (("Администратор: " if principal["role"] == "admin" else item.participant.full_name + ": ") + row.text)[:240],
        f"/?openConversation={item.id}&type=personal",
        include_admin=principal["role"] != "admin",
    )
    publish_personal_update(db, item, message_id=row.id, sender_role=principal["role"])
    return {
        "id": row.id,
        "sender": row.sender.full_name if row.sender else "Администратор",
        "sender_role": row.sender_role,
        "can_delete": True,
        "content_type": "text",
        "text": row.text,
        "metadata": {},
        "delivery_status": "delivered",
        "panel_read_at": None,
        "created_at": row.created_at.isoformat(),
    }


@router.delete("/panel/personal-messages/{message_id}")
def delete_personal_message(message_id: int, principal: PanelUser, db: Db):
    row = db.get(PersonalMessage, message_id)
    if not row:
        raise HTTPException(status_code=404, detail="Сообщение не найдено")
    item = _personal_conversation(db, principal, row.conversation_id)
    if row.sender_role != principal["role"] or (
        principal["role"] != "admin" and row.sender_id != principal.get("user_id")
    ):
        raise HTTPException(status_code=403, detail="Можно удалить только собственное сообщение")
    db.delete(row)
    db.commit()
    publish_personal_update(db, item, message_id=message_id, action="delete")
    return {"ok": True, "deleted_message_id": message_id}
