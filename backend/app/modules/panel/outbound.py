"""Отправка сообщений и вложений из веб-панели."""

import json
import logging
from typing import Annotated

from fastapi import (
    APIRouter,
    BackgroundTasks,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
)
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError

from app.infrastructure.storage.media import (
    delete_message_media,
)
from app.models import (
    Message,
)
from app.modules.communication.contracts import (
    MessageKind,
    MessengerPlatform,
    OutboundMedia,
)
from app.modules.conversations.service import (
    publish_conversation_update,
)
from app.modules.dependencies import Db, PanelUser
from app.modules.messaging.moderation import text_contains_contact_data
from app.modules.messaging.service import (
    _panel_message_dict,
    _panel_visible_conversation,
)
from app.modules.notifications.service import schedule_push
from app.request_validation import message_payload

from .delivery import (
    deliver_panel_message,
    panel_sender_and_recipients,
    refresh_teacher_panel_after_web_delivery,
    save_panel_messenger_results,
    store_panel_attachment,
)

logger = logging.getLogger(__name__)
router = APIRouter()


def _message_response(row: Message, principal: dict) -> dict:
    return _panel_message_dict(row, expose_internal_metadata=(principal["role"] == "admin"), principal=principal)


def _find_sent_message(db, principal, conversation, sender, client_message_id, *, legacy_metadata=False):
    """Ищет уже сохранённое сообщение с тем же client_message_id (защита от повторной отправки)."""
    same_id = [Message.client_message_id == client_message_id]
    if legacy_metadata:
        same_id.append(func.json_extract(Message.metadata_json, "$.client_message_id") == client_message_id)
    return db.scalar(
        select(Message).where(
            Message.conversation_id == conversation.id,
            Message.sender_id == sender.id,
            Message.sender_role == principal["role"],
            or_(*same_id),
        ).limit(1),
    )


def _commit_message(db, row, principal, conversation, sender, client_message_id, on_conflict=None):
    """Сохраняет сообщение. При гонке по client_message_id возвращает уже существующее, иначе None."""
    db.add(row)
    try:
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
    db.refresh(row)
    return None


async def _publish_and_deliver(
    request, background_tasks, db, principal, conversation, parties, row, *, preview, kind, media=None,
):
    """Публикует событие и пуш, затем доставляет сообщение в мессенджеры."""
    sender, recipients, student, teacher = parties
    role = principal["role"]
    # Событие публикуем сразу после сохранения, не ожидая Telegram.
    publish_conversation_update(db, conversation, message_id=row.id, sender_role=role)
    push_recipients = [student.id, teacher.id] if role == "admin" else ([student.id] if role == "teacher" else [teacher.id])
    schedule_push(
        db, push_recipients, "Новое сообщение · UknowApp",
        (sender.full_name + ": " + preview)[:240],
        f"/?openConversation={conversation.id}", include_admin=role != "admin",
    )

    bot = getattr(request.app.state, "telegram_bot", None)
    communication = getattr(request.app.state, "communication", None)
    messenger_results = await deliver_panel_message(
        db, communication, row, conversation, recipients, role, student, row.text, kind, media=media,
    )
    save_panel_messenger_results(db, row, conversation, messenger_results)

    if bot and MessengerPlatform.TELEGRAM.value in messenger_results:
        background_tasks.add_task(
            refresh_teacher_panel_after_web_delivery, bot, teacher.id, conversation.id,
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
        metadata_json=json.dumps({
            "source_mode": "web",
            "web_sender_role": principal["role"],
            **({"client_message_id": client_message_id} if client_message_id else {}),
        }, ensure_ascii=False),
        client_message_id=client_message_id,
        delivery_status="delivered",
    )
    existing = _commit_message(db, row, principal, conversation, sender, client_message_id)
    if existing:
        return _message_response(existing, principal)
    await _publish_and_deliver(
        request, background_tasks, db, principal, conversation, parties, row,
        preview=body, kind=MessageKind.TEXT,
    )
    return _message_response(row, principal)


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
    size, original_name, relative, mime_type, kind = await store_panel_attachment(
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
    existing = _commit_message(
        db, row, principal, conversation, sender, client_message_id,
        on_conflict=lambda: delete_message_media(json.dumps({"media": media}, ensure_ascii=False)),
    )
    if existing:
        return _message_response(existing, principal)
    await _publish_and_deliver(
        request, background_tasks, db, principal, conversation, parties, row,
        preview=row.text or "Отправлено вложение",
        kind=MessageKind(kind),
        media=OutboundMedia(
            storage_key=relative.as_posix(),
            file_name=original_name,
            mime_type=mime_type,
        ),
    )
    return _message_response(row, principal)
