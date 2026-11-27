"""Отправка сообщений и вложений из веб-панели."""

import logging
from typing import Annotated

from fastapi import (
    APIRouter,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
)
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError

from app.infrastructure.storage.media import (
    delete_message_media,
)
from app.infrastructure.storage.message_metadata import (
    encode_message_metadata,
    metadata_value,
)
from app.infrastructure.storage.uploads import store_panel_attachment
from app.models import (
    Message,
)
from app.modules.communication.contracts import MessageKind
from app.modules.communication.outbox import enqueue_web_delivery
from app.modules.conversations.service import (
    publish_conversation_update,
)
from app.modules.dependencies import Db, PanelUser
from app.modules.messaging.moderation import text_contains_contact_data
from app.modules.messaging.service import (
    panel_message_dict,
    panel_visible_conversation,
)
from app.modules.notifications.content import PUSH_TITLE, push_body
from app.modules.notifications.service import schedule_push
from app.request_validation import message_payload

from .delivery import panel_sender_and_recipients

logger = logging.getLogger(__name__)
router = APIRouter()


def _message_response(row: Message, principal: dict) -> dict:
    return panel_message_dict(row, expose_internal_metadata=(principal["role"] == "admin"), principal=principal)


def _find_sent_message(db, principal, conversation, sender, client_message_id, *, legacy_metadata=False):
    """Ищет уже сохранённое сообщение с тем же client_message_id (защита от повторной отправки)."""
    same_id = [Message.client_message_id == client_message_id]
    if legacy_metadata:
        same_id.append(metadata_value(db, Message.metadata_json, "client_message_id") == client_message_id)
    return db.scalar(
        select(Message).where(
            Message.conversation_id == conversation.id,
            Message.sender_id == sender.id,
            Message.sender_role == principal["role"],
            or_(*same_id),
        ).limit(1),
    )


def _commit_message(db, row, principal, conversation, sender, client_message_id, on_conflict=None, *, delivery_platforms=()):
    """Сохраняет сообщение. При гонке по client_message_id возвращает уже существующее, иначе None."""
    db.add(row)
    try:
        if delivery_platforms:
            db.flush()
            enqueue_web_delivery(db, row, delivery_platforms)
        db.commit()
    except IntegrityError:
        db.rollback()
        if on_conflict:
            on_conflict()
        existing = client_message_id and _find_sent_message(
            db, principal, conversation, sender, client_message_id,
        )
        if existing:
            return existing
        raise
    # flush/commit заполняют ID и значения по умолчанию.
    return None


def _publish_message_update(
    request, db, principal, conversation, parties, row, *, preview, kind,
):
    """Публикует событие и пуш, затем будит очередь доставки."""
    sender, _recipients, student, teacher = parties
    role = principal["role"]
    if role == "admin":
        logger.info("Admin posted message id=%s in conversation id=%s", row.id, conversation.id)
    # Событие публикуем сразу после сохранения, не ожидая внешней доставки.
    publish_conversation_update(db, conversation, message_id=row.id, sender_role=role)
    push_recipients = [student.id, teacher.id] if role == "admin" else ([student.id] if role == "teacher" else [teacher.id])
    admin_receiver = student if role == "teacher" else teacher
    schedule_push(
        db, push_recipients, PUSH_TITLE,
        push_body(sender.full_name, preview, kind=kind.value),
        f"/?openConversation={conversation.id}", include_admin=role != "admin",
        admin_body=(
            push_body(
                sender.full_name, preview, recipient_name=admin_receiver.full_name,
                kind=kind.value,
            ) if role != "admin" else None
        ),
    )

    gateway = getattr(request.app.state, "bots_gateway", None)
    if gateway is not None and gateway.platforms:
        gateway.wake_outbox()


@router.post("/panel/conversations/{conversation_id}/messages", status_code=201)
def send_panel_message(
    conversation_id: int,
    payload: dict,
    request: Request,
    principal: PanelUser,
    db: Db,
):
    payload = message_payload(payload)
    # Сначала сохраняем сообщение в БД, затем отправляем его адресатам через Gateway.
    conversation = panel_visible_conversation(db, principal, conversation_id)
    body = payload["text"].strip()
    if text_contains_contact_data(body):
        raise HTTPException(status_code=400, detail="Контактные данные нельзя отправлять через чат UknowApp")
    if not body:
        raise HTTPException(status_code=400, detail="Введите текст сообщения")

    parties = panel_sender_and_recipients(db, principal, conversation)
    sender = parties[0]

    client_message_id = payload.get("client_message_id")
    if client_message_id:
        existing = _find_sent_message(
            db, principal, conversation, sender, client_message_id, legacy_metadata=True,
        )
        if existing:
            return _message_response(existing, principal)

    row = Message(
        conversation_id=conversation.id,
        sender_id=sender.id,
        sender_role=principal["role"],
        content_type="text",
        text=body,
        metadata_json=encode_message_metadata({
            "source_mode": "web",
        }),
        client_message_id=client_message_id,
        delivery_status="delivered",
    )
    existing = _commit_message(
        db, row, principal, conversation, sender, client_message_id,
        delivery_platforms=getattr(getattr(request.app.state, "bots_gateway", None), "platforms", ()),
    )
    if existing:
        return _message_response(existing, principal)
    _publish_message_update(
        request, db, principal, conversation, parties, row,
        preview=body, kind=MessageKind.TEXT,
    )
    return _message_response(row, principal)


@router.post("/panel/conversations/{conversation_id}/attachments", status_code=201)
def send_panel_attachment(
    conversation_id: int,
    request: Request,
    principal: PanelUser,
    db: Db,
    file: Annotated[UploadFile, File()],
    text: Annotated[str, Form()] = "",
    client_message_id: Annotated[str | None, Form()] = None,
):
    # Ограничиваем размер до чтения файла целиком и сохраняем локальную копию для веб-панели.
    conversation = panel_visible_conversation(db, principal, conversation_id)
    if len(text or "") > 3900:
        raise HTTPException(status_code=400, detail="Текст к вложению слишком длинный")
    parties = panel_sender_and_recipients(db, principal, conversation)
    sender = parties[0]
    client_message_id = (client_message_id or "").strip() or None
    if client_message_id and len(client_message_id) > 64:
        raise HTTPException(status_code=400, detail="Некорректный ID отправки")
    if client_message_id:
        existing = _find_sent_message(db, principal, conversation, sender, client_message_id)
        if existing:
            return _message_response(existing, principal)

    if text_contains_contact_data((text or "").strip()):
        raise HTTPException(status_code=400, detail="Контактные данные нельзя отправлять через чат UknowApp")
    size, original_name, relative, mime_type, kind = store_panel_attachment(
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
        metadata_json=encode_message_metadata({
            "source_mode": "web",
            "media": media,
        }),
        client_message_id=client_message_id,
        delivery_status="delivered",
    )
    existing = _commit_message(
        db, row, principal, conversation, sender, client_message_id,
        on_conflict=lambda: delete_message_media(encode_message_metadata({"media": media})),
        delivery_platforms=getattr(getattr(request.app.state, "bots_gateway", None), "platforms", ()),
    )
    if existing:
        return _message_response(existing, principal)
    _publish_message_update(
        request, db, principal, conversation, parties, row,
        preview=row.text,
        kind=MessageKind(kind),
    )
    return _message_response(row, principal)
