"""HTTP API веб-панели и обмена сообщениями."""

import asyncio

from starlette.concurrency import run_in_threadpool
import json
import logging
import mimetypes
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from aiogram.exceptions import TelegramAPIError
from fastapi import (
    APIRouter,
    BackgroundTasks,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
)
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, load_only, selectinload

from app.core.database import SessionLocal
from app.event_hub import (
    replay_chat_updates,
    subscribe_chat_updates,
    unsubscribe_chat_updates,
)
from app.infrastructure.storage.media import (
    MAX_ATTACHMENT_BYTES, ATTACHMENT_SIZE_ERROR,
    MEDIA_DIR,
    delete_message_media,
    media_content_disposition,
    safe_media_type,
)
from app.models import (
    Assignment,
    Conversation,
    Message,
    PersonalConversation,
    PersonalMessage,
    StudentTelegramGroup,
    TeacherSession,
    User,
)
from app.modules.communication.accounts import get_messenger_account, get_messenger_pair
from app.modules.communication.contracts import (
    MessageKind,
    MessengerError,
    MessengerPlatform,
    OutboundMedia,
    OutboundMessage,
)
from app.modules.communication.service import record_messenger_delivery
from app.modules.conversations.service import (
    conversation_dicts,
    publish_conversation_update,
)
from app.modules.dependencies import Db, PanelUser
from app.modules.messaging.moderation import text_contains_contact_data
from app.modules.messaging.service import (
    _panel_message_dict,
    _panel_message_status_dict,
    _panel_visible_conversation,
)
from app.modules.notifications.service import schedule_push
from app.modules.personal_chat.service import (
    _personal_conversation,
    _personal_conversation_dict,
    publish_personal_update,
)
from app.request_validation import message_payload, personal_conversation_payload

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

def _panel_student_telegram_target(
    db: Session,
    conversation: Conversation,
    account=None,
) -> dict | None:
    student = conversation.student
    account = account or get_messenger_account(db, student.id, MessengerPlatform.TELEGRAM)
    if not account:
        return None
    target = {"chat_id": account.external_chat_id or account.external_user_id}

    teacher_reply = db.execute(
        select(Message.id, Message.created_at, Message.metadata_json)
        .where(
            Message.conversation_id == conversation.id,
            Message.sender_role == "teacher",
            Message.delivery_status != "blocked_contact",
        )
        .order_by(Message.created_at.desc(), Message.id.desc())
        .limit(1),
    ).first()

    admin_replies = db.execute(
        select(Message.id, Message.created_at, Message.metadata_json)
        .where(
            Message.conversation_id == conversation.id,
            Message.sender_role == "admin",
            Message.delivery_status != "blocked_contact",
        )
        .order_by(Message.created_at.desc(), Message.id.desc()),
    ).all()
    admin_reply = None
    for candidate in admin_replies:
        metadata = json.loads(candidate.metadata_json or "{}")
        deliveries = (
            (metadata.get("messenger_deliveries") or {}).get("telegram", {}).get("delivered")
            or metadata.get("telegram_deliveries")
            or []
        )
        if not deliveries or any(delivery.get("user_id") == student.id for delivery in deliveries):
            admin_reply = candidate
            break

    last_reply = max(
        (item for item in (teacher_reply, admin_reply) if item is not None),
        key=lambda item: (item.created_at, item.id),
        default=None,
    )
    incoming_query = select(Message.metadata_json).where(
        Message.conversation_id == conversation.id,
        Message.sender_role == "student",
    )
    if last_reply is not None:
        incoming_query = incoming_query.where(
            or_(
                Message.created_at > last_reply.created_at,
                and_(
                    Message.created_at == last_reply.created_at,
                    Message.id > last_reply.id,
                ),
            ),
        )
    incoming_metadata = db.scalar(
        incoming_query
        .order_by(Message.created_at.desc(), Message.id.desc())
        .limit(1),
    )
    if incoming_metadata is not None:
        incoming_meta = json.loads(incoming_metadata or "{}")
        if incoming_meta.get("source_mode") == "group_topic":
            try:
                group_chat_id = int(incoming_meta["source_chat_id"])
                thread_id = int(incoming_meta["source_thread_id"])
            except (KeyError, TypeError, ValueError):
                return target
            linked_topic = db.scalar(select(StudentTelegramGroup).where(
                StudentTelegramGroup.student_id == student.id,
                StudentTelegramGroup.chat_id == group_chat_id,
                StudentTelegramGroup.thread_id == thread_id,
            ))
            if linked_topic:
                return {"chat_id": group_chat_id, "message_thread_id": thread_id}
        return target

    if last_reply is not None:
        response_meta = json.loads(last_reply.metadata_json or "{}")
        for delivery in response_meta.get("telegram_deliveries") or []:
            if delivery.get("user_id") != student.id or delivery.get("thread_id") is None:
                continue
            try:
                group_chat_id = int(delivery["chat_id"])
                thread_id = int(delivery["thread_id"])
            except (KeyError, TypeError, ValueError):
                return target
            linked_topic = db.scalar(select(StudentTelegramGroup).where(
                StudentTelegramGroup.student_id == student.id,
                StudentTelegramGroup.chat_id == group_chat_id,
                StudentTelegramGroup.thread_id == thread_id,
            ))
            if linked_topic:
                return {"chat_id": group_chat_id, "message_thread_id": thread_id}

    current_binding = db.get(StudentTelegramGroup, student.id)
    if current_binding:
        return {
            "chat_id": current_binding.chat_id,
            "message_thread_id": current_binding.thread_id,
        }
    return target

@router.get("/panel/me")
def panel_me(principal: PanelUser, db: Db):
    if principal["role"] == "admin":
        return {"role": "admin", "full_name": "Администратор"}
    user = db.get(User, principal["user_id"])
    if (
        not user
        or user.role != principal["role"]
        or user.role not in {"teacher", "student"}
    ):
        raise HTTPException(status_code=401, detail="Учётная запись недоступна")
    return {"role": user.role, "id": user.id, "full_name": user.full_name}


@router.get("/panel/events")
async def panel_events(request: Request, principal: PanelUser, db: Db):
    """Передавать события и восстанавливать пропущенные."""
    queue = subscribe_chat_updates(principal)
    try:
        cursor = int(request.headers.get("last-event-id", "0") or 0)
    except ValueError:
        cursor = 0
    replay = replay_chat_updates(db, principal, cursor) if cursor else []
    # Не удерживаем соединение с БД во время SSE-подписки.
    db.rollback()

    async def event_stream():
        try:
            yield "retry: 1500\n\n"
            for event_id, payload in replay:
                yield f"id: {event_id}\nevent: update\ndata: {payload}\n\n"
            while not await request.is_disconnected():
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=15)
                except TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                try:
                    event_id = json.loads(payload).get("event_id")
                except (TypeError, ValueError):
                    event_id = None
                if event_id is not None:
                    yield f"id: {event_id}\n"
                yield "event: update\ndata: " + payload + "\n\n"
        finally:
            unsubscribe_chat_updates(queue)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/panel/conversations")
def panel_conversations(principal: PanelUser, db: Db):
    statement = (
        select(Conversation)
        .options(
            selectinload(Conversation.teacher),
            selectinload(Conversation.student),
        )
        .join(Assignment, Conversation.assignment_id == Assignment.id)
        .join(User, Assignment.student_id == User.id)
        .where(
            Assignment.active.is_(True),
            Conversation.status == "active",
        )
        .order_by(Conversation.created_at.desc(), Conversation.id.desc())
    )
    if principal["role"] == "teacher":
        statement = statement.where(Assignment.teacher_id == principal["user_id"])
    elif principal["role"] == "student":
        statement = statement.where(Assignment.student_id == principal["user_id"]).limit(1)
    conversations = db.scalars(statement).all()
    return conversation_dicts(
        db,
        conversations,
        include_telegram_ids=(principal["role"] == "admin"),
        viewer_role=principal["role"],
    )


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
    return _personal_summaries(db, items, principal["role"])


def _personal_summaries(db: Session, items: list[PersonalConversation], role: str) -> list[dict]:
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
    return _personal_summaries(db, [item], principal["role"])[0]


@router.get("/panel/personal-conversations/{conversation_id}/summary")
def personal_conversation_summary(conversation_id: int, principal: PanelUser, db: Db):
    item = _personal_conversation(db, principal, conversation_id)
    return _personal_summaries(db, [item], principal["role"])[0]


@router.get("/panel/conversations/{conversation_id}/summary")
def panel_conversation_summary(conversation_id: int, principal: PanelUser, db: Db):
    conversation = _panel_visible_conversation(db, principal, conversation_id)
    return conversation_dicts(
        db, [conversation], include_telegram_ids=(principal["role"] == "admin"),
        viewer_role=principal["role"],
    )[0]


def _personal_message_dict(row: PersonalMessage, principal: dict) -> dict:
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


def _personal_message_status_dict(row: PersonalMessage) -> dict:
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
    return [_personal_message_dict(row, principal) for row in rows]


@router.get("/panel/personal-messages/{message_id}")
def personal_message(message_id: int, principal: PanelUser, db: Db):
    row = db.get(PersonalMessage, message_id)
    if not row:
        raise HTTPException(status_code=404, detail="Сообщение не найдено")
    _personal_conversation(db, principal, row.conversation_id)
    return _personal_message_dict(row, principal)


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
            return _personal_message_dict(existing, principal)

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
                return _personal_message_dict(existing, principal)
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


@router.get("/panel/conversations/{conversation_id}/messages")
def panel_messages(conversation_id: int, principal: PanelUser, db: Db, after_id: int = 0):
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
            now = datetime.now(UTC).isoformat()
            for row in unread:
                metadata = json.loads(row.metadata_json or "{}")
                metadata[read_key] = now
                row.metadata_json = json.dumps(metadata, ensure_ascii=False)
            db.commit()
            publish_conversation_update(
                db, conversation, action="read", actor_role=principal["role"],
                message_ids=[row.id for row in unread], read_at=now,
            )
    rows = db.scalars(
        select(Message)
        .where(Message.conversation_id == conversation.id, Message.id > after_id)
        .order_by(Message.created_at, Message.id),
    ).all()
    return [
        _panel_message_dict(
            item,
            expose_internal_metadata=(principal["role"] == "admin"),
            principal=principal,
        )
        for item in rows
    ]


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
        "messages": [_personal_message_dict(row, principal) for row in new_rows],
        "updated_messages": [_personal_message_status_dict(row) for row in updated_rows],
        "summary": _personal_summaries(db, [item], principal["role"])[0],
    }


@router.get("/panel/messages/{message_id}")
def panel_message(message_id: int, principal: PanelUser, db: Db):
    item = db.get(Message, message_id)
    if not item:
        raise HTTPException(status_code=404, detail="Сообщение не найдено")
    _panel_visible_conversation(db, principal, item.conversation_id)
    return _panel_message_dict(
        item,
        expose_internal_metadata=(principal["role"] == "admin"),
        principal=principal,
    )


@router.delete("/panel/messages/{message_id}")
async def delete_panel_message(
    message_id: int,
    request: Request,
    principal: PanelUser,
    db: Db,
):
    item = db.get(Message, message_id)
    if not item:
        raise HTTPException(status_code=404, detail="Сообщение не найдено")

    conversation = _panel_visible_conversation(db, principal, item.conversation_id)
    owns_message = (
        item.sender_role == principal["role"]
        and (
            principal["role"] == "admin"
            or item.sender_id == principal.get("user_id")
        )
    )
    if not owns_message:
        raise HTTPException(status_code=403, detail="Можно удалить только собственное сообщение")

    metadata = json.loads(item.metadata_json or "{}")
    deliveries_by_platform = metadata.get("messenger_deliveries") or {}
    if not deliveries_by_platform and metadata.get("telegram_deliveries"):
        # Поддерживаем сообщения без общего журнала внешних доставок.
        deliveries_by_platform = {
            MessengerPlatform.TELEGRAM.value: {
                "delivered": metadata["telegram_deliveries"],
            },
        }

    communication = getattr(request.app.state, "communication", None)
    messenger_deleted = 0
    messenger_failed = 0
    telegram_deleted = 0
    telegram_failed = 0

    # Удаляем внешние копии через адаптеры; UknowApp остаётся источником данных.
    for platform_value, result in deliveries_by_platform.items():
        try:
            platform = MessengerPlatform(platform_value)
        except ValueError:
            continue
        for delivery in result.get("delivered", []):
            external_chat_id = (
                delivery.get("external_chat_id") or delivery.get("chat_id")
            )
            external_message_id = (
                delivery.get("external_message_id")
                or delivery.get("telegram_message_id")
            )
            if not external_chat_id or not external_message_id:
                messenger_failed += 1
                if platform == MessengerPlatform.TELEGRAM:
                    telegram_failed += 1
                continue
            try:
                if not communication or not communication.has_adapter(platform):
                    raise RuntimeError("Messenger adapter is disabled")
                await communication.delete_message(
                    platform=platform,
                    external_chat_id=str(external_chat_id),
                    external_message_id=str(external_message_id),
                )
                messenger_deleted += 1
                if platform == MessengerPlatform.TELEGRAM:
                    telegram_deleted += 1
            except (MessengerError, RuntimeError, NotImplementedError) as exc:
                messenger_failed += 1
                if platform == MessengerPlatform.TELEGRAM:
                    telegram_failed += 1
                logger.warning(
                    "Could not delete messenger copy (platform=%s message_id=%s error_type=%s)",
                    platform.value,
                    item.id,
                    type(exc).__name__,
                )

    delete_message_media(item.metadata_json)
    db.delete(item)
    db.commit()
    publish_conversation_update(db, conversation, message_id=message_id, action="delete")

    return {
        "ok": True,
        "deleted_message_id": message_id,
        "messenger_deleted": messenger_deleted,
        "messenger_failed": messenger_failed,
        "telegram_deleted": telegram_deleted,
        "telegram_failed": telegram_failed,
    }


@router.get("/panel/messages/{message_id}/media")
def panel_message_media(message_id: int, principal: PanelUser, db: Db):
    item = db.get(Message, message_id)
    if not item:
        raise HTTPException(status_code=404, detail="Сообщение не найдено")
    _panel_visible_conversation(db, principal, item.conversation_id)
    metadata = json.loads(item.metadata_json or "{}")
    media = metadata.get("media") or {}
    relative = media.get("local_path")
    if not relative or media.get("archive_status") != "stored":
        raise HTTPException(status_code=404, detail="Локальная копия вложения недоступна")
    root = MEDIA_DIR.resolve()
    path = (root / relative).resolve()
    if root not in path.parents or not path.is_file():
        raise HTTPException(status_code=404, detail="Файл вложения не найден")
    return FileResponse(
        path,
        media_type=safe_media_type(media.get("mime_type")),
        filename=media.get("file_name") or path.name,
        content_disposition_type=media_content_disposition(media.get("kind"), media.get("mime_type")),
        headers={"X-Content-Type-Options": "nosniff", "Content-Security-Policy": "sandbox"},
    )


def _panel_sender_and_recipients(db: Session, principal: dict, conversation: Conversation):
    """Определить отправителя и адресатов в Telegram."""
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


def _save_panel_messenger_results(
    db: Session,
    row: Message,
    conversation: Conversation,
    results: dict[str, dict[str, list[dict]]],
) -> None:
    if not results:
        return
    metadata = json.loads(row.metadata_json or "{}")
    for platform, result in results.items():
        record_messenger_delivery(
            metadata,
            platform,
            delivered=result.get("delivered", []),
            errors=result.get("errors", []),
        )
    row.metadata_json = json.dumps(metadata, ensure_ascii=False)
    # Статус сообщения отражает хранение в UknowApp, не внешнюю доставку.
    row.delivery_status = "delivered"
    db.commit()
    publish_conversation_update(
        db, conversation, message_id=row.id, action="delivery",
        sender_role=row.sender_role,
    )


async def _deliver_panel_message(
    db: Session,
    communication,
    row: Message,
    conversation: Conversation,
    recipients: list[tuple[User, str]],
    sender_role: str,
    student: User,
    body: str,
    content_type: MessageKind,
    media: OutboundMedia | None = None,
) -> dict[str, dict[str, list[dict]]]:
    """Отправлять через канал только при привязке обоих участников."""
    results: dict[str, dict[str, list[dict]]] = {}
    if communication is None:
        return results

    for platform in communication.platforms:
        teacher_account, student_account = get_messenger_pair(
            db, conversation.teacher_id, conversation.student_id, platform,
        )
        # Отправляем только когда оба участника привязаны к каналу.
        if not teacher_account or not student_account:
            continue

        accounts_by_user = {
            conversation.teacher_id: teacher_account,
            conversation.student_id: student_account,
        }
        student_telegram_target = (
            _panel_student_telegram_target(db, conversation, student_account)
            if platform == MessengerPlatform.TELEGRAM
            and any(role == "student" for _, role in recipients)
            else None
        )
        delivered: list[dict] = []
        errors: list[dict] = []
        for recipient, recipient_role in recipients:
            account = accounts_by_user[recipient.id]
            target = (
                student_telegram_target
                if platform == MessengerPlatform.TELEGRAM and recipient_role == "student"
                else {
                    "chat_id": account.external_chat_id or account.external_user_id,
                }
            )
            if not target:
                errors.append({
                    "name": recipient.full_name,
                    "role": recipient_role,
                    "reason": "Не удалось определить адресата в " + platform.value.upper(),
                })
                continue

            if content_type == MessageKind.TEXT:
                outgoing_text = (
                    body if sender_role == "teacher"
                    else "Сообщение от ученика " + student.full_name + ":\n" + body
                    if sender_role == "student"
                    else "Сообщение от администратора школы:\n" + body
                )
            else:
                outgoing_text = (
                    body.strip()[:1024] if sender_role == "teacher"
                    else (
                        "Сообщение от ученика " + student.full_name
                        + ((": " + body) if body else "")
                        if sender_role == "student"
                        else "От администратора школы" + ((": " + body) if body else "")
                    )
                )

            try:
                sent = await communication.send(OutboundMessage(
                    platform=platform,
                    external_chat_id=str(target["chat_id"]),
                    external_thread_id=(
                        str(target["message_thread_id"])
                        if target.get("message_thread_id") is not None else None
                    ),
                    content_type=content_type,
                    text=outgoing_text,
                    media=media,
                    idempotency_key=(
                        f"panel-message:{row.id}:platform:{platform.value}:"
                        f"recipient:{recipient.id}"
                    ),
                ))
                delivered.append({
                    "user_id": recipient.id,
                    "external_message_id": str(sent.external_message_id),
                    "external_chat_id": str(target["chat_id"]),
                    "external_thread_id": (
                        str(target["message_thread_id"])
                        if target.get("message_thread_id") is not None else None
                    ),
                })
            except (MessengerError, OSError, ValueError, TypeError, RuntimeError) as exc:
                error_type = getattr(exc, "provider_error_type", type(exc).__name__)
                logger.warning(
                    "Messenger delivery failed (platform=%s conversation_id=%s error_type=%s)",
                    platform.value, conversation.id, error_type,
                )
                errors.append({
                    "name": recipient.full_name,
                    "role": recipient_role,
                    "reason": "ошибка " + platform.value.upper() + " (" + error_type + ")",
                })

        results[platform.value] = {"delivered": delivered, "errors": errors}

    return results


async def _store_panel_attachment(file: UploadFile, conversation_id: int):
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

    relative = Path(str(conversation_id)) / (uuid.uuid4().hex + suffix)
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
        size = await run_in_threadpool(copy_upload)
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


async def _refresh_teacher_panel_after_web_delivery(bot, teacher_id: int, conversation_id: int) -> None:
    """Обновить панель преподавателя в фоне."""
    if not bot:
        return
    try:
        with SessionLocal() as db:
            teacher = db.get(User, teacher_id)
            conversation = db.get(Conversation, conversation_id)
            if not teacher or not conversation:
                return
            if not get_messenger_account(db, teacher.id, MessengerPlatform.TELEGRAM):
                return
            from app.modules.telegram.teacher import (
                clear_teacher_session,
                update_teacher_panel,
            )
            current_session = db.get(TeacherSession, teacher.id)
            if current_session and current_session.conversation_id != conversation.id:
                clear_teacher_session(db, teacher)
            await update_teacher_panel(bot, db, teacher)
    except (TelegramAPIError, SQLAlchemyError) as exc:
        logger.warning(
            "Could not refresh teacher panel after web delivery "
            "(teacher_id=%s conversation_id=%s error_type=%s)",
            teacher_id, conversation_id, type(exc).__name__,
        )


@router.post("/panel/conversations/{conversation_id}/messages", status_code=201)
async def send_panel_message(
    conversation_id: int,
    payload: dict,
    request: Request,
    principal: PanelUser,
    db: Db,
    background_tasks: BackgroundTasks,
):
    payload = message_payload(payload)
    # Сначала сохраняем сообщение в БД, затем отправляем его адресатам в Telegram.
    conversation = _panel_visible_conversation(db, principal, conversation_id)
    body = payload["text"].strip()
    if text_contains_contact_data(body):
        raise HTTPException(status_code=400, detail="Контактные данные нельзя отправлять через чат UknowApp")
    if not body:
        raise HTTPException(status_code=400, detail="Введите текст сообщения")

    sender, recipients, student, teacher = _panel_sender_and_recipients(db, principal, conversation)

    client_message_id = payload.get("client_message_id")
    if client_message_id:
        existing = db.scalar(
            select(Message).where(
                Message.conversation_id == conversation.id,
                Message.sender_id == sender.id,
                Message.sender_role == principal["role"],
                or_(
                    Message.client_message_id == client_message_id,
                    func.json_extract(Message.metadata_json, "$.client_message_id") == client_message_id,
                ),
            ).limit(1),
        )
        if existing:
            return _panel_message_dict(
                existing,
                expose_internal_metadata=(principal["role"] == "admin"),
                principal=principal,
            )

    row = Message(
        conversation_id=conversation.id,
        sender_id=sender.id,
        sender_role=principal["role"],
        content_type="text",
        text=body,
        metadata_json=json.dumps({
            "source_mode": "web",
            "web_sender_role": principal["role"],
            **({"client_message_id": client_message_id} if client_message_id else {}),
        }, ensure_ascii=False),
        client_message_id=client_message_id,
        delivery_status="delivered",
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        if client_message_id:
            existing = db.scalar(
                select(Message).where(
                    Message.conversation_id == conversation.id,
                    Message.sender_id == sender.id,
                    Message.sender_role == principal["role"],
                    Message.client_message_id == client_message_id,
                ).limit(1),
            )
            if existing:
                return _panel_message_dict(
                    existing,
                    expose_internal_metadata=(principal["role"] == "admin"),
                    principal=principal,
                )
        raise
    db.refresh(row)
    # Событие публикуем сразу после сохранения, не ожидая Telegram.
    publish_conversation_update(db, conversation, message_id=row.id, sender_role=principal["role"])
    push_recipients = [student.id, teacher.id] if principal["role"] == "admin" else ([student.id] if principal["role"] == "teacher" else [teacher.id])
    schedule_push(
        db, push_recipients, "Новое сообщение · UknowApp",
        (sender.full_name + ": " + (body or "Новое сообщение"))[:240],
        f"/?openConversation={conversation.id}", include_admin=principal["role"] != "admin",
    )

    bot = getattr(request.app.state, "telegram_bot", None)
    communication = getattr(request.app.state, "communication", None)
    messenger_results = await _deliver_panel_message(
        db,
        communication,
        row,
        conversation,
        recipients,
        principal["role"],
        student,
        body,
        MessageKind.TEXT,
    )
    _save_panel_messenger_results(db, row, conversation, messenger_results)

    if bot and MessengerPlatform.TELEGRAM.value in messenger_results:
        background_tasks.add_task(
            _refresh_teacher_panel_after_web_delivery,
            bot,
            teacher.id,
            conversation.id,
        )

    return _panel_message_dict(row, expose_internal_metadata=(principal["role"] == "admin"), principal=principal)


@router.post("/panel/conversations/{conversation_id}/attachments", status_code=201)
async def send_panel_attachment(
    conversation_id: int,
    request: Request,
    principal: PanelUser,
    db: Db,
    background_tasks: BackgroundTasks,
    file: Annotated[UploadFile, File()],
    text: Annotated[str, Form()] = "",
    client_message_id: Annotated[str | None, Form()] = None,
):
    # Ограничиваем размер до чтения файла целиком и сохраняем локальную копию для веб-панели.
    conversation = _panel_visible_conversation(db, principal, conversation_id)
    if len(text or "") > 3900:
        raise HTTPException(status_code=400, detail="Текст к вложению слишком длинный")
    sender, recipients, student, teacher = _panel_sender_and_recipients(db, principal, conversation)
    client_message_id = (client_message_id or "").strip() or None
    if client_message_id and len(client_message_id) > 64:
        raise HTTPException(status_code=400, detail="Некорректный ID отправки")
    if client_message_id:
        existing = db.scalar(
            select(Message).where(
                Message.conversation_id == conversation.id,
                Message.sender_id == sender.id,
                Message.sender_role == principal["role"],
                Message.client_message_id == client_message_id,
            ).limit(1),
        )
        if existing:
            return _panel_message_dict(
                existing,
                expose_internal_metadata=(principal["role"] == "admin"),
                principal=principal,
            )

    if text_contains_contact_data((text or "").strip()):
        raise HTTPException(status_code=400, detail="Контактные данные нельзя отправлять через чат UknowApp")
    size, original_name, relative, mime_type, kind = await _store_panel_attachment(
        file, conversation.id,
    )

    media = {
        "kind": kind,
        "file_name": original_name,
        "mime_type": mime_type,
        "file_size": size,
        "local_path": relative.as_posix(),
        "archive_status": "stored",
    }
    row = Message(
        conversation_id=conversation.id,
        sender_id=sender.id,
        sender_role=principal["role"],
        content_type=kind,
        text=(text or "").strip(),
        metadata_json=json.dumps({
            "source_mode": "web",
            "web_sender_role": principal["role"],
            **({"client_message_id": client_message_id} if client_message_id else {}),
            "media": media,
        }, ensure_ascii=False),
        client_message_id=client_message_id,
        delivery_status="delivered",
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        delete_message_media(json.dumps({"media": media}, ensure_ascii=False))
        if client_message_id:
            existing = db.scalar(
                select(Message).where(
                    Message.conversation_id == conversation.id,
                    Message.sender_id == sender.id,
                    Message.sender_role == principal["role"],
                    Message.client_message_id == client_message_id,
                ).limit(1),
            )
            if existing:
                return _panel_message_dict(
                    existing,
                    expose_internal_metadata=(principal["role"] == "admin"),
                    principal=principal,
                )
        raise
    db.refresh(row)
    publish_conversation_update(
        db, conversation, message_id=row.id, sender_role=principal["role"],
    )
    push_recipients = [student.id, teacher.id] if principal["role"] == "admin" else ([student.id] if principal["role"] == "teacher" else [teacher.id])
    schedule_push(
        db, push_recipients, "Новое сообщение · UknowApp",
        (sender.full_name + ": " + (row.text or "Отправлено вложение"))[:240],
        f"/?openConversation={conversation.id}", include_admin=principal["role"] != "admin",
    )

    bot = getattr(request.app.state, "telegram_bot", None)
    communication = getattr(request.app.state, "communication", None)
    messenger_results = await _deliver_panel_message(
        db,
        communication,
        row,
        conversation,
        recipients,
        principal["role"],
        student,
        row.text,
        MessageKind(kind),
        media=OutboundMedia(
            storage_key=relative.as_posix(),
            file_name=original_name,
            mime_type=mime_type,
        ),
    )
    _save_panel_messenger_results(db, row, conversation, messenger_results)

    if bot and MessengerPlatform.TELEGRAM.value in messenger_results:
        background_tasks.add_task(
            _refresh_teacher_panel_after_web_delivery,
            bot,
            teacher.id,
            conversation.id,
        )
    return _panel_message_dict(row, expose_internal_metadata=(principal["role"] == "admin"), principal=principal)
