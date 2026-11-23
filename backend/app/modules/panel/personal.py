"""Личные диалоги администратора с участниками."""

import json
import logging
import shutil
from typing import Annotated

from fastapi import (
    APIRouter,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, selectinload

from app.core.database import SessionLocal
from app.event_hub import publish_chat_update
from app.infrastructure.storage.media import (
    MEDIA_DIR,
    attachment_response,
    delete_message_media,
)
from app.infrastructure.storage.message_metadata import encode_message_metadata
from app.models import (
    PersonalConversation,
    PersonalMediaCleanup,
    PersonalMessage,
    User,
)
from app.modules.dependencies import Db, PanelUser
from app.modules.notifications.content import PUSH_TITLE, push_body
from app.modules.notifications.service import schedule_push
from app.modules.personal_chat.service import (
    _personal_conversation,
    _personal_conversation_dict,
    publish_personal_update,
)
from app.request_validation import message_payload, personal_conversation_payload

from .delivery import store_panel_attachment
from .read_state import mark_personal_read

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/panel/personal-conversations")
def personal_conversations(principal: PanelUser, db: Db):
    statement = select(PersonalConversation).options(
        joinedload(PersonalConversation.participant),
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


@router.delete("/panel/personal-conversations/{conversation_id}")
def delete_personal_conversation(conversation_id: int, principal: PanelUser, db: Db):
    """Навсегда удалить личный чат, его сообщения и локальные вложения."""
    if principal["role"] != "admin":
        raise HTTPException(status_code=403, detail="Удалять личные диалоги может только администратор")
    item = _personal_conversation(db, principal, conversation_id)
    participant_id = item.participant_id

    # Сначала убираем все дочерние записи в одной транзакции (внешний ключ
    # personal_messages.conversation_id не настроен на ON DELETE CASCADE).
    db.add(PersonalMediaCleanup(conversation_id=conversation_id))
    result = db.execute(delete(PersonalMessage).where(PersonalMessage.conversation_id == conversation_id))
    db.delete(item)
    db.commit()
    publish_chat_update(
        conversation_id, conversation_type="personal", action="delete_conversation",
        audience={"participant_id": participant_id}, db=db,
    )
    cleaned = clean_personal_media(db, conversation_id)
    return {"ok": True, "deleted_conversation_id": conversation_id,
            "deleted_messages": result.rowcount, "media_cleanup_pending": not cleaned}


def clean_personal_media(db: Session, conversation_id: int) -> bool:
    directory = MEDIA_DIR / "personal" / str(conversation_id)
    try:
        if directory.parent.is_symlink():
            raise OSError("Unexpected symlink for personal media root")
        if directory.is_symlink():
            directory.unlink()
        else:
            shutil.rmtree(directory)
    except FileNotFoundError:
        # Another worker may also be cleaning this directory.
        if directory.exists() or directory.is_symlink():
            return False
    except OSError:
        logger.exception("Personal media cleanup pending: conversation_id=%s", conversation_id)
        return False
    db.execute(delete(PersonalMediaCleanup).where(PersonalMediaCleanup.conversation_id == conversation_id))
    db.commit()
    return True


def retry_personal_media_cleanup():
    with SessionLocal() as db:
        for conversation_id in db.scalars(select(PersonalMediaCleanup.conversation_id)).all():
            clean_personal_media(db, conversation_id)


@router.get("/panel/personal-conversations/{conversation_id}/summary")
def personal_conversation_summary(conversation_id: int, principal: PanelUser, db: Db):
    item = _personal_conversation(db, principal, conversation_id)
    return personal_summaries(db, [item], principal["role"])[0]


def personal_message_dict(row: PersonalMessage, principal: dict) -> dict:
    metadata = json.loads(row.metadata_json or "{}")
    if metadata.get("media"):
        metadata["media"] = {key: value for key, value in metadata["media"].items() if key != "local_path"}
    return {
        "id": row.id,
        "sender": row.sender.full_name if row.sender else "Администратор",
        "sender_role": row.sender_role,
        "can_delete": row.sender_role == principal["role"] and (
            principal["role"] == "admin" or row.sender_id == principal.get("user_id")
        ),
        "content_type": metadata.get("media", {}).get("kind", "text"),
        "text": row.text,
        "metadata": metadata,
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
def personal_messages(conversation_id: int, principal: PanelUser, db: Db, after_id: int = 0,
                   limit: int | None = Query(None, ge=1, le=100), before_id: int | None = None,
                   mark_read: bool = True):
    item = _personal_conversation(db, principal, conversation_id)
    query = select(PersonalMessage).options(selectinload(PersonalMessage.sender)).where(
        PersonalMessage.conversation_id == item.id, PersonalMessage.id > after_id,
    )
    if before_id is not None:
        query = query.where(PersonalMessage.id < before_id)
    if limit is None:
        if mark_read:
            mark_personal_read(db, item, principal, after_id)
        rows = db.scalars(query.order_by(PersonalMessage.created_at, PersonalMessage.id)).all()
    else:
        rows = list(reversed(db.scalars(query.order_by(PersonalMessage.id.desc()).limit(limit)).all()))
        if mark_read:
            mark_personal_read(db, item, principal, after_id, [row.id for row in rows])
    return [personal_message_dict(row, principal) for row in rows]


@router.get("/panel/personal-messages/{message_id}")
def personal_message(message_id: int, principal: PanelUser, db: Db):
    row = db.get(PersonalMessage, message_id)
    if not row:
        raise HTTPException(status_code=404, detail="Сообщение не найдено")
    _personal_conversation(db, principal, row.conversation_id)
    return personal_message_dict(row, principal)


def _personal_sender_id(db, principal, item):
    """Автор сообщения: администратор — без пользователя, остальные — только владелец диалога."""
    if principal["role"] == "admin":
        return None
    sender = db.get(User, principal["user_id"])
    if not sender or sender.id != item.participant_id:
        raise HTTPException(status_code=403, detail="Нет доступа к личному диалогу")
    return sender.id


def _find_personal_message(db, principal, conversation_id, client_message_id):
    """Ищет уже сохранённое сообщение с тем же client_message_id (защита от повторной отправки)."""
    return db.scalar(
        select(PersonalMessage).where(
            PersonalMessage.conversation_id == conversation_id,
            PersonalMessage.sender_role == principal["role"],
            PersonalMessage.client_message_id == client_message_id,
        ).limit(1),
    )


def _commit_personal_message(db, row, principal, item, client_message_id, on_failure=None):
    """Сохраняет сообщение. При гонке по client_message_id возвращает существующее, иначе None."""
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        if on_failure:
            on_failure()
        existing = client_message_id and _find_personal_message(db, principal, item.id, client_message_id)
        if existing:
            return existing
        raise
    except Exception:
        db.rollback()
        if on_failure:
            on_failure()
        raise
    db.refresh(row)
    return None


def _notify_personal(db, item, principal, row, preview, *, kind="text"):
    """Личные сообщения: только имя отправителя и короткий текст."""
    is_admin = principal["role"] == "admin"
    sender_name = "Администратор" if is_admin else item.participant.full_name
    schedule_push(
        db,
        [item.participant_id] if is_admin else [],
        PUSH_TITLE,
        push_body(sender_name, preview, kind=kind),
        f"/?openConversation={item.id}&type=personal",
        include_admin=not is_admin,
    )
    publish_personal_update(db, item, message_id=row.id, sender_role=principal["role"])


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
    sender_id = _personal_sender_id(db, principal, item)
    client_message_id = payload.get("client_message_id")
    if client_message_id:
        existing = _find_personal_message(db, principal, item.id, client_message_id)
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
    existing = _commit_personal_message(db, row, principal, item, client_message_id)
    if existing:
        return personal_message_dict(existing, principal)
    _notify_personal(db, item, principal, row, row.text)
    return personal_message_dict(row, principal)


@router.get("/panel/personal-messages/{message_id}/media")
def personal_message_media(message_id: int, request: Request, principal: PanelUser, db: Db):
    """Только администратор и участник диалога могут получить его вложение."""
    row = db.get(PersonalMessage, message_id)
    if not row:
        raise HTTPException(status_code=404, detail="Сообщение не найдено")
    _personal_conversation(db, principal, row.conversation_id)
    media = json.loads(row.metadata_json or "{}").get("media") or {}
    if media.get("archive_status") != "stored" or not media.get("local_path"):
        raise HTTPException(status_code=404, detail="Вложение недоступно")
    root = MEDIA_DIR.resolve()
    path = (root / media["local_path"]).resolve()
    if root not in path.parents or not path.is_file():
        raise HTTPException(status_code=404, detail="Файл не найден")
    return attachment_response(request, path, media)


@router.post("/panel/personal-conversations/{conversation_id}/attachments", status_code=201)
async def send_personal_attachment(
    conversation_id: int,
    principal: PanelUser,
    db: Db,
    file: Annotated[UploadFile, File()],
    text: Annotated[str, Form()] = "",
    client_message_id: Annotated[str | None, Form()] = None,
):
    item = _personal_conversation(db, principal, conversation_id)
    if principal["role"] not in {"admin", "teacher", "student"}:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    if len(text or "") > 3900:
        raise HTTPException(status_code=400, detail="Текст к вложению слишком длинный")
    sender_id = _personal_sender_id(db, principal, item)
    client_message_id = (client_message_id or "").strip() or None
    if client_message_id and len(client_message_id) > 64:
        raise HTTPException(status_code=400, detail="Некорректный ID отправки")
    if client_message_id:
        existing = _find_personal_message(db, principal, conversation_id, client_message_id)
        if existing:
            return personal_message_dict(existing, principal)

    size, name, relative, mime_type, kind = await store_panel_attachment(
        file, conversation_id, personal=True,
    )
    media = {
        "kind": kind,
        "file_name": name,
        "mime_type": mime_type,
        "file_size": size,
        "local_path": relative.as_posix(),
        "archive_status": "stored",
    }
    metadata_json = encode_message_metadata({"media": media})
    row = PersonalMessage(
        conversation_id=item.id,
        sender_id=sender_id,
        sender_role=principal["role"],
        text=(text or "").strip(),
        metadata_json=metadata_json,
        client_message_id=client_message_id,
    )
    existing = _commit_personal_message(
        db, row, principal, item, client_message_id,
        on_failure=lambda: delete_message_media(metadata_json),
    )
    if existing:
        return personal_message_dict(existing, principal)
    _notify_personal(db, item, principal, row, row.text, kind=kind)
    return personal_message_dict(row, principal)


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
    media_metadata = row.metadata_json
    db.delete(row)
    db.commit()
    delete_message_media(media_metadata)
    publish_personal_update(db, item, message_id=message_id, action="delete")
    return {"ok": True, "deleted_message_id": message_id}
