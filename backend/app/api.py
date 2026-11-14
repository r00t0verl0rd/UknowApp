import hashlib
import json
import secrets
import mimetypes
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse
from aiogram.types import BufferedInputFile
from sqlalchemy import select
from sqlalchemy.orm import aliased
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .config import ADMIN_USERNAME
from .database import SessionLocal
from .media_storage import MEDIA_DIR, delete_message_media, safe_media_type, media_content_disposition
from .models import Assignment, ConnectionCode, Conversation, Message, StudentTelegramGroup, TeacherPanel, TeacherSession, User
from .schemas import AssignmentCreate, LoginRequest, PanelMessageCreate, UserCreate, UserUpdate
from .security import (
    authenticate_panel_user,
    check_login_rate_limit,
    clear_panel_cookies,
    clear_username_failures,
    create_panel_session,
    hash_web_password,
    record_failed_login,
    require_admin,
    require_panel_user,
    revoke_panel_session,
    verify_request_origin,
)
from .telegram_common import text_contains_contact_data

router = APIRouter(prefix="/api")


def get_db():
    with SessionLocal() as db:
        yield db


Admin = Annotated[str, Depends(require_admin)]
PanelUser = Annotated[dict, Depends(require_panel_user)]
Db = Annotated[Session, Depends(get_db)]


def user_dict(user: User, include_telegram_id: bool = True) -> dict:
    return {
        "id": user.id,
        "full_name": user.full_name,
        "web_username": (user.web_username or user.full_name) if user.role == "teacher" else None,
        "role": user.role,
        "telegram_id": user.telegram_id if include_telegram_id else None,
        "active": user.active,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "has_web_password": bool(user.web_password_hash),
    }


def validate_teacher_username(db: Session, username: str, exclude_user_id: Optional[int] = None) -> str:
    cleaned = (username or "").strip()
    if len(cleaned) < 2 or len(cleaned) > 160:
        raise HTTPException(status_code=400, detail="Логин учителя должен содержать от 2 до 160 символов")
    if cleaned.casefold() == ADMIN_USERNAME.casefold():
        raise HTTPException(status_code=409, detail="Этот логин зарезервирован для администратора")
    teachers = db.scalars(select(User).where(User.role == "teacher")).all()
    for teacher in teachers:
        if teacher.id == exclude_user_id:
            continue
        existing = (teacher.web_username or teacher.full_name).strip()
        if existing.casefold() == cleaned.casefold():
            raise HTTPException(status_code=409, detail="Этот логин уже используется другим учителем")
    return cleaned


def conversation_dict(
    db: Session, conversation: Conversation, include_telegram_ids: bool = True
) -> dict:
    assignment = conversation.assignment
    last_message = db.scalar(
        select(Message).where(Message.conversation_id == conversation.id)
        .order_by(Message.created_at.desc(), Message.id.desc()).limit(1)
    )
    count = len(db.scalars(select(Message.id).where(Message.conversation_id == conversation.id)).all())
    return {
        "id": conversation.id,
        "status": conversation.status,
        "created_at": conversation.created_at.isoformat(),
        "teacher": user_dict(assignment.teacher, include_telegram_id=include_telegram_ids),
        "student": user_dict(assignment.student, include_telegram_id=include_telegram_ids),
        "last_message": (
            (last_message.text or "Сообщение") if last_message.content_type == "text"
            else (
                (json.loads(last_message.metadata_json or "{}").get("media") or {}).get("file_name")
                or {
                    "photo": "🖼 Фотография",
                    "voice": "🎤 Голосовое сообщение",
                    "audio": "🎵 Аудио",
                    "video": "🎬 Видео",
                    "video_note": "⭕ Видеосообщение",
                    "document": "📎 Документ",
                    "sticker": "Стикер",
                    "animation": "GIF-анимация",
                }.get(last_message.content_type, "📎 Вложение")
            ) + ((": " + last_message.text) if last_message.text else "")
        ) if last_message else "Переписка пока пуста",
        "last_message_at": last_message.created_at.isoformat() if last_message else None,
        "message_count": count,
        "unread_count": sum(1 for row in db.scalars(select(Message).where(Message.conversation_id == conversation.id)).all() if row.sender_role == "student" and json.loads(row.metadata_json or "{}").get("teacher_read_at") is None),
    }


@router.post("/auth/login")
def login(payload: LoginRequest, request: Request, response: Response, db: Db):
    verify_request_origin(request)
    check_login_rate_limit(request, payload.username)
    identity = authenticate_panel_user(payload.username, payload.password)
    if not identity:
        record_failed_login(request, payload.username)
        raise HTTPException(status_code=401, detail="Неверный логин или пароль")
    clear_username_failures(request, payload.username)
    create_panel_session(db, identity, request, response)
    return {"ok": True, **identity}


@router.post("/auth/logout")
def logout(request: Request, response: Response, db: Db):
    verify_request_origin(request)
    revoke_panel_session(request, db)
    clear_panel_cookies(request, response)
    return {"ok": True}


@router.get("/health")
def health():
    return {"status": "ok", "service": "uknowapp"}


@router.get("/admin/overview")
def overview(_: Admin, db: Db):
    users = db.scalars(select(User).order_by(User.full_name)).all()
    assignments = db.scalars(
        select(Assignment).where(Assignment.active.is_(True)).order_by(Assignment.created_at.desc())
    ).all()
    active_conversations = db.scalars(select(Conversation).where(Conversation.status == "active")).all()

    students_by_teacher: dict[int, list[dict]] = {}
    for assignment in assignments:
        if not assignment.teacher.active or not assignment.student.active:
            continue
        students_by_teacher.setdefault(assignment.teacher_id, []).append(user_dict(assignment.student))

    teachers = []
    for user in users:
        if user.role != "teacher" or not user.active:
            continue
        teachers.append({**user_dict(user), "students": students_by_teacher.get(user.id, [])})

    return {
        "admin": {"label": "Администратор", "role": "admin"},
        "counts": {
            "teachers": sum(1 for user in users if user.role == "teacher" and user.active),
            "students": sum(1 for user in users if user.role == "student" and user.active),
            "assignments": len(assignments),
            "conversations": len(active_conversations),
            "messages": db.query(Message).count(),
        },
        "teachers": teachers,
    }


@router.get("/admin/users")
def list_users(_: Admin, db: Db):
    users = db.scalars(select(User).where(User.role.in_(["teacher", "student"])).order_by(User.role, User.full_name)).all()
    return [user_dict(user) for user in users]


@router.post("/admin/users", status_code=201)
def create_user(payload: UserCreate, _: Admin, db: Db):
    full_name = payload.full_name.strip()
    web_username = validate_teacher_username(db, payload.web_username or full_name) if payload.role == "teacher" else None
    user = User(full_name=full_name, web_username=web_username, role=payload.role, telegram_id=payload.telegram_id)
    if payload.web_password:
        if payload.role != "teacher":
            raise HTTPException(status_code=400, detail="Пароль веб-панели можно задать только учителю")
        user.web_password_hash = hash_web_password(payload.web_password)
    db.add(user)
    try:
        db.commit()
        db.refresh(user)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Этот Telegram ID уже используется")
    return user_dict(user)


@router.patch("/admin/users/{user_id}")
def update_user(user_id: int, payload: UserUpdate, _: Admin, db: Db):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    changes = payload.model_dump(exclude_unset=True)
    new_web_password = changes.pop("web_password", None)
    requested_web_username = changes.pop("web_username", None)
    target_role = changes.get("role", user.role)
    if new_web_password:
        if target_role != "teacher":
            raise HTTPException(status_code=400, detail="Пароль веб-панели можно задать только учителю")
        user.web_password_hash = hash_web_password(new_web_password)

    if target_role == "teacher":
        previous_username = user.web_username or user.full_name
        if requested_web_username is not None:
            target_username = requested_web_username
        elif "full_name" in changes and previous_username.strip().casefold() == user.full_name.strip().casefold():
            target_username = changes["full_name"].strip()
        else:
            target_username = previous_username
        user.web_username = validate_teacher_username(db, target_username, exclude_user_id=user.id)
    else:
        user.web_username = None

    role_changed = "role" in changes and changes["role"] != user.role
    if role_changed:
        if changes.get("role") != "teacher":
            user.web_password_hash = None
        db.query(TeacherPanel).filter(TeacherPanel.teacher_id == user.id).delete(synchronize_session=False)
        assignments = db.scalars(select(Assignment).where(Assignment.active.is_(True), (Assignment.teacher_id == user.id) | (Assignment.student_id == user.id))).all()
        now = datetime.now(timezone.utc)
        for assignment in assignments:
            assignment.active = False
            assignment.closed_at = now
            if assignment.conversation:
                assignment.conversation.status = "closed"
        db.query(TeacherSession).filter(TeacherSession.teacher_id == user.id).delete(synchronize_session=False)
    for field, value in changes.items():
        if field == "full_name" and value is not None:
            value = value.strip()
        setattr(user, field, value)
    if changes.get("active") is False:
        related = db.scalars(
            select(Assignment).where(
                Assignment.active.is_(True),
                (Assignment.teacher_id == user.id) | (Assignment.student_id == user.id),
            )
        ).all()
        for assignment in related:
            assignment.active = False
            assignment.closed_at = datetime.now(timezone.utc)
            if assignment.conversation:
                assignment.conversation.status = "closed"
    try:
        db.commit()
        db.refresh(user)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Этот Telegram ID уже используется")
    return user_dict(user)


@router.post("/admin/users/{user_id}/disconnect-telegram")
def disconnect_telegram(user_id: int, _: Admin, db: Db):
    user = db.get(User, user_id)
    if not user or user.role not in {"teacher", "student"}:
        raise HTTPException(status_code=404, detail="Учитель или ученик не найден")
    if not user.telegram_id:
        raise HTTPException(status_code=409, detail="Telegram уже отключён")

    disconnected_telegram_id = user.telegram_id
    now = datetime.now(timezone.utc)

    # Remove the binding without deleting the account, assignments or chat history.
    user.telegram_id = None

    # A disconnected teacher must select a conversation again after reconnecting.
    if user.role == "teacher":
        db.query(TeacherSession).filter(
            TeacherSession.teacher_id == user.id
        ).delete(synchronize_session=False)

    # Prevent any previously generated, unused code from being reused.
    db.query(ConnectionCode).filter(
        ConnectionCode.user_id == user.id,
        ConnectionCode.used_at.is_(None),
    ).update({ConnectionCode.used_at: now}, synchronize_session=False)

    db.commit()
    db.refresh(user)
    return {
        "ok": True,
        "user": user_dict(user),
        "disconnected_telegram_id": disconnected_telegram_id,
    }


@router.delete("/admin/users/{user_id}")
def delete_user(user_id: int, _: Admin, db: Db):
    user = db.get(User, user_id)
    if not user or user.role not in {"teacher", "student"}:
        raise HTTPException(status_code=404, detail="Учитель или ученик не найден")

    assignments = db.scalars(
        select(Assignment).where(
            (Assignment.teacher_id == user.id) | (Assignment.student_id == user.id)
        )
    ).all()
    conversation_ids = [item.conversation.id for item in assignments if item.conversation]
    if conversation_ids:
        media_rows = db.scalars(select(Message).where(Message.conversation_id.in_(conversation_ids))).all()
        for media_row in media_rows:
            delete_message_media(media_row.metadata_json)
        db.query(TeacherSession).filter(
            TeacherSession.conversation_id.in_(conversation_ids)
        ).delete(synchronize_session=False)
        db.query(Message).filter(
            Message.conversation_id.in_(conversation_ids)
        ).delete(synchronize_session=False)
        db.query(Conversation).filter(
            Conversation.id.in_(conversation_ids)
        ).delete(synchronize_session=False)

    db.query(TeacherSession).filter(
        TeacherSession.teacher_id == user.id
    ).delete(synchronize_session=False)
    db.query(TeacherPanel).filter(TeacherPanel.teacher_id == user.id).delete(synchronize_session=False)
    if assignments:
        db.query(Assignment).filter(
            Assignment.id.in_([item.id for item in assignments])
        ).delete(synchronize_session=False)
    db.query(ConnectionCode).filter(
        ConnectionCode.user_id == user.id
    ).delete(synchronize_session=False)
    db.delete(user)
    db.commit()
    return {"ok": True, "deleted_user_id": user_id, "deleted_conversations": len(conversation_ids)}


@router.post("/admin/users/{user_id}/connection-code")
def generate_connection_code(user_id: int, _: Admin, db: Db):
    user = db.get(User, user_id)
    if not user or user.role not in {"teacher", "student"}:
        raise HTTPException(status_code=404, detail="Учитель или ученик не найден")
    if not user.active:
        raise HTTPException(status_code=400, detail="Нельзя подключить отключённого пользователя")
    if user.telegram_id:
        raise HTTPException(
            status_code=409,
            detail="Telegram уже подключён. Сначала очистите Telegram ID в профиле пользователя.",
        )

    now = datetime.now(timezone.utc)
    # New code invalidates every previous unused code for this account.
    previous_codes = db.scalars(
        select(ConnectionCode).where(
            ConnectionCode.user_id == user.id,
            ConnectionCode.used_at.is_(None),
        )
    ).all()
    for previous in previous_codes:
        previous.used_at = now

    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    raw_code = "".join(secrets.choice(alphabet) for _ in range(8))
    code_hash = hashlib.sha256(raw_code.encode("utf-8")).hexdigest()
    expires_at = now + timedelta(minutes=15)

    db.add(ConnectionCode(
        user_id=user.id,
        code_hash=code_hash,
        created_at=now,
        expires_at=expires_at,
    ))
    db.commit()

    return {
        "code": raw_code[:4] + "-" + raw_code[4:],
        "expires_at": expires_at.isoformat(),
        "lifetime_minutes": 15,
        "user": user.full_name,
        "role": user.role,
    }


@router.post("/admin/assignments", status_code=201)
def assign_student(payload: AssignmentCreate, _: Admin, db: Db):
    teacher = db.get(User, payload.teacher_id)
    student = db.get(User, payload.student_id)
    if not teacher or teacher.role != "teacher" or not teacher.active:
        raise HTTPException(status_code=400, detail="Выберите активного учителя")
    if not student or student.role != "student" or not student.active:
        raise HTTPException(status_code=400, detail="Выберите активного ученика")

    previous = db.scalars(
        select(Assignment).where(Assignment.student_id == student.id, Assignment.active.is_(True))
    ).all()
    now = datetime.now(timezone.utc)
    for assignment in previous:
        assignment.active = False
        assignment.closed_at = now
        if assignment.conversation:
            assignment.conversation.status = "closed"

    assignment = Assignment(teacher_id=teacher.id, student_id=student.id, active=True)
    db.add(assignment)
    db.flush()
    conversation = Conversation(assignment_id=assignment.id, status="active")
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return conversation_dict(db, conversation)


@router.get("/admin/conversations")
def list_conversations(_: Admin, db: Db):
    # Keep this list in sync with the school graph:
    # only active assignments between active teachers and active students are visible.
    teacher = aliased(User)
    student = aliased(User)
    conversations = db.scalars(
        select(Conversation)
        .join(Assignment, Conversation.assignment_id == Assignment.id)
        .join(teacher, Assignment.teacher_id == teacher.id)
        .join(student, Assignment.student_id == student.id)
        .where(
            Assignment.active.is_(True),
            teacher.active.is_(True),
            student.active.is_(True),
        )
        .order_by(Conversation.created_at.desc())
    ).all()
    return [conversation_dict(db, item) for item in conversations]


@router.get("/admin/conversations/{conversation_id}/messages")
def list_messages(conversation_id: int, _: Admin, db: Db):
    conversation = db.get(Conversation, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Переписка не найдена")
    rows = db.scalars(
        select(Message).where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at, Message.id)
    ).all()
    return [{
        "id": item.id,
        "sender": item.sender.full_name,
        "sender_role": item.sender_role,
        "content_type": item.content_type,
        "text": item.text,
        "metadata": json.loads(item.metadata_json or "{}"),
        "delivery_status": item.delivery_status,
        "created_at": item.created_at.isoformat(),
    } for item in rows]



@router.get("/admin/messages/{message_id}/media")
def get_message_media(message_id: int, _: Admin, db: Db):
    item = db.get(Message, message_id)
    if not item:
        raise HTTPException(status_code=404, detail="Сообщение не найдено")
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


def _panel_conversation_dict(db: Session, conversation: Conversation, principal: dict) -> dict:
    return conversation_dict(
        db, conversation, include_telegram_ids=(principal["role"] == "admin")
    )


def _panel_visible_conversation(db: Session, principal: dict, conversation_id: int) -> Conversation:
    conversation = db.get(Conversation, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Переписка не найдена")
    if principal["role"] == "teacher":
        assignment = conversation.assignment
        if (
            assignment.teacher_id != principal["user_id"]
            or not assignment.active
            or not assignment.teacher.active
            or not assignment.student.active
            or conversation.status != "active"
        ):
            raise HTTPException(status_code=404, detail="Переписка не найдена")
    return conversation


def _panel_message_dict(item: Message, expose_internal_metadata: bool = True) -> dict:
    metadata = json.loads(item.metadata_json or "{}")
    if not expose_internal_metadata:
        for key in (
            "source_chat_id", "source_thread_id", "telegram_deliveries",
            "telegram_delivery_errors", "teacher_inbox_media_message_id",
            "teacher_inbox_notice_message_id",
        ):
            metadata.pop(key, None)
        for key in ("photo", "document", "audio", "video", "voice", "video_note", "sticker", "animation"):
            attachment = metadata.get(key)
            if isinstance(attachment, dict):
                attachment.pop("file_id", None)
                attachment.pop("file_unique_id", None)
        media = metadata.get("media")
        if isinstance(media, dict):
            metadata["media"] = {
                key: media.get(key)
                for key in ("kind", "file_name", "mime_type", "file_size", "archive_status")
                if key in media
            }
    return {
        "id": item.id,
        "sender": item.sender.full_name if item.sender else "Администратор",
        "sender_role": item.sender_role,
        "content_type": item.content_type,
        "text": item.text,
        "metadata": metadata,
        "delivery_status": item.delivery_status,
        "created_at": item.created_at.isoformat(),
    }


def _panel_student_telegram_target(
    db: Session,
    conversation: Conversation,
    rows: list[Message],
) -> Optional[dict]:
    student = conversation.assignment.student
    if not student.telegram_id:
        return None
    target = {"chat_id": student.telegram_id}
    last_reply_index = max(
        (
            i for i, item in enumerate(rows)
            if item.sender_role in {"teacher", "admin"}
            and item.delivery_status in {"delivered", "partial"}
            and (
                item.sender_role == "teacher"
                or any(
                    delivery.get("user_id") == student.id
                    for delivery in (json.loads(item.metadata_json or "{}").get("telegram_deliveries") or [])
                )
                or not json.loads(item.metadata_json or "{}").get("telegram_deliveries")
            )
        ),
        default=-1,
    )
    for incoming in reversed(rows[last_reply_index + 1:]):
        if incoming.sender_role != "student":
            continue
        incoming_meta = json.loads(incoming.metadata_json or "{}")
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

    # Preserve the group topic used by the last answer after an administrator
    # has intervened and there is no newer student message.
    if last_reply_index >= 0:
        response_meta = json.loads(rows[last_reply_index].metadata_json or "{}")
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
    return target


@router.get("/panel/me")
def panel_me(principal: PanelUser, db: Db):
    if principal["role"] == "admin":
        return {"role": "admin", "full_name": "Администратор"}
    teacher = db.get(User, principal["user_id"])
    if not teacher or not teacher.active or teacher.role != "teacher":
        raise HTTPException(status_code=401, detail="Учётная запись недоступна")
    return {"role": "teacher", "id": teacher.id, "full_name": teacher.full_name}


@router.get("/panel/conversations")
def panel_conversations(principal: PanelUser, db: Db):
    statement = (
        select(Conversation)
        .join(Assignment, Conversation.assignment_id == Assignment.id)
        .join(User, Assignment.student_id == User.id)
        .where(Assignment.active.is_(True), User.active.is_(True), Conversation.status == "active")
        .order_by(Conversation.created_at.desc())
    )
    if principal["role"] == "teacher":
        statement = statement.where(Assignment.teacher_id == principal["user_id"])
    conversations = db.scalars(statement).all()
    return [_panel_conversation_dict(db, item, principal) for item in conversations]


@router.get("/panel/conversations/{conversation_id}/messages")
def panel_messages(conversation_id: int, principal: PanelUser, db: Db):
    conversation = _panel_visible_conversation(db, principal, conversation_id)
    rows = db.scalars(
        select(Message).where(Message.conversation_id == conversation.id)
        .order_by(Message.created_at, Message.id)
    ).all()
    if principal["role"] == "teacher":
        now = datetime.now(timezone.utc).isoformat()
        changed = False
        for row in rows:
            if row.sender_role == "student":
                metadata = json.loads(row.metadata_json or "{}")
                if metadata.get("teacher_read_at") is None:
                    metadata["teacher_read_at"] = now
                    row.metadata_json = json.dumps(metadata, ensure_ascii=False)
                    changed = True
        if changed:
            db.commit()
    return [
        _panel_message_dict(item, expose_internal_metadata=(principal["role"] == "admin"))
        for item in rows
    ]


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


@router.post("/panel/conversations/{conversation_id}/messages", status_code=201)
async def send_panel_message(
    conversation_id: int,
    payload: PanelMessageCreate,
    request: Request,
    principal: PanelUser,
    db: Db,
):
    conversation = _panel_visible_conversation(db, principal, conversation_id)
    body = payload.text.strip()
    if text_contains_contact_data(body):
        raise HTTPException(status_code=400, detail="Контактные данные нельзя отправлять через чат UknowApp")
    if not body:
        raise HTTPException(status_code=400, detail="Введите текст сообщения")

    student = conversation.assignment.student
    teacher = conversation.assignment.teacher
    if principal["role"] == "teacher":
        sender = db.get(User, principal["user_id"])
        recipients = [(student, "student")]
    else:
        sender = db.scalar(select(User).where(User.role == "admin").order_by(User.id).limit(1))
        if not sender:
            sender = User(full_name="Администратор", role="admin", active=True)
            db.add(sender)
            db.flush()
        recipients = [(student, "student"), (teacher, "teacher")]

    rows = db.scalars(
        select(Message).where(Message.conversation_id == conversation.id)
        .order_by(Message.created_at, Message.id)
    ).all()
    student_target = _panel_student_telegram_target(db, conversation, rows)

    row = Message(
        conversation_id=conversation.id,
        sender_id=sender.id,
        sender_role=principal["role"],
        content_type="text",
        text=body,
        metadata_json=json.dumps({"source_mode": "web", "web_sender_role": principal["role"]}, ensure_ascii=False),
        delivery_status="pending",
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    bot = getattr(request.app.state, "telegram_bot", None)
    delivery_errors = []
    delivered = []
    if bot:
        for recipient, recipient_role in recipients:
            if not recipient.active or not recipient.telegram_id:
                delivery_errors.append(recipient.full_name + ": Telegram не подключён")
                continue
            try:
                prefix = (
                    "Сообщение от учителя " + sender.full_name + ":\n"
                    if principal["role"] == "teacher"
                    else "Сообщение от администратора школы:\n"
                )
                target = student_target if recipient_role == "student" else {"chat_id": recipient.telegram_id}
                if not target:
                    delivery_errors.append(recipient.full_name + ": Telegram не подключён")
                    continue
                sent = await bot.send_message(**target, text=prefix + body)
                delivered.append({
                    "user_id": recipient.id,
                    "telegram_message_id": sent.message_id,
                    "chat_id": target["chat_id"],
                    "thread_id": target.get("message_thread_id"),
                })
            except Exception as exc:
                logger.warning("Telegram delivery failed for conversation_id=%s: %s", conversation.id, type(exc).__name__)
                delivery_errors.append(recipient.full_name + ": ошибка Telegram (" + type(exc).__name__ + ")")
    else:
        delivery_errors.append("Telegram-бот не подключён к веб-приложению")

    metadata = json.loads(row.metadata_json or "{}")
    metadata["telegram_deliveries"] = delivered
    if delivery_errors:
        metadata["telegram_delivery_errors"] = delivery_errors
    row.metadata_json = json.dumps(metadata, ensure_ascii=False)
    row.delivery_status = "delivered" if delivered and not delivery_errors else ("partial" if delivered else "failed")
    db.commit()

    if bot and teacher.telegram_id:
        try:
            from .telegram_teacher import clear_teacher_session, update_teacher_panel
            current_session = db.get(TeacherSession, teacher.id)
            if current_session and current_session.conversation_id != conversation.id:
                clear_teacher_session(db, teacher)
            await update_teacher_panel(bot, db, teacher)
        except Exception:
            # Message is already persisted; a panel refresh failure must not undo it.
            pass

    return _panel_message_dict(row, expose_internal_metadata=(principal["role"] == "admin"))


@router.post("/panel/conversations/{conversation_id}/attachments", status_code=201)
async def send_panel_attachment(
    conversation_id: int,
    request: Request,
    principal: PanelUser,
    db: Db,
    file: UploadFile = File(...),
    text: str = Form(default=""),
):
    conversation = _panel_visible_conversation(db, principal, conversation_id)
    if len(text or "") > 3900:
        raise HTTPException(status_code=400, detail="Текст к вложению слишком длинный")
    student = conversation.assignment.student
    teacher = conversation.assignment.teacher
    sender = db.get(User, principal["user_id"]) if principal["role"] == "teacher" else None
    if principal["role"] == "admin":
        sender = db.scalar(select(User).where(User.role == "admin").order_by(User.id).limit(1))
        if not sender:
            sender = User(full_name="Администратор", role="admin", active=True)
            db.add(sender)
            db.flush()
    if not sender:
        raise HTTPException(status_code=401, detail="Учётная запись недоступна")

    if text_contains_contact_data((text or "").strip()):
        raise HTTPException(status_code=400, detail="Контактные данные нельзя отправлять через чат UknowApp")
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > 22 * 1024 * 1024:
                raise HTTPException(status_code=413, detail="Максимальный размер файла — 20 МБ")
        except ValueError:
            raise HTTPException(status_code=400, detail="Некорректный Content-Length")
    content = await file.read(20 * 1024 * 1024 + 1)
    if len(content) > 20 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Максимальный размер файла — 20 МБ")
    if not content:
        raise HTTPException(status_code=400, detail="Файл пустой")
    original_name = (file.filename or "attachment").replace("\\", "/").rsplit("/", 1)[-1]
    original_name = "".join(char for char in original_name if ord(char) >= 32 and char not in "\r\n")[:180].strip() or "attachment"
    suffix = re.sub(r"[^A-Za-z0-9.]", "", Path(original_name).suffix)[:12]
    if not suffix:
        suffix = mimetypes.guess_extension(file.content_type or "") or ".bin"
    relative = Path(str(conversation.id)) / (uuid.uuid4().hex + suffix)
    target_path = (MEDIA_DIR / relative).resolve()
    root = MEDIA_DIR.resolve()
    if root not in target_path.parents:
        raise HTTPException(status_code=400, detail="Недопустимое имя файла")
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_bytes(content)

    reported_mime_type = file.content_type or mimetypes.guess_type(original_name)[0]
    mime_type = safe_media_type(reported_mime_type)
    if mime_type.startswith("image/"):
        kind = "photo"
    elif mime_type.startswith("video/"):
        kind = "video"
    elif mime_type.startswith("audio/"):
        kind = "voice" if mime_type in {"audio/ogg", "audio/opus"} else "audio"
    else:
        kind = "document"

    media = {
        "kind": kind,
        "file_name": original_name,
        "mime_type": mime_type,
        "file_size": len(content),
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
            "media": media,
        }, ensure_ascii=False),
        delivery_status="pending",
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    rows = db.scalars(
        select(Message).where(Message.conversation_id == conversation.id)
        .order_by(Message.created_at, Message.id)
    ).all()
    student_target = _panel_student_telegram_target(db, conversation, rows[:-1])

    recipients = [(student, "student")]
    if principal["role"] == "admin":
        recipients.append((teacher, "teacher"))
    bot = getattr(request.app.state, "telegram_bot", None)
    delivery_errors = []
    delivered = []
    if bot:
        for recipient, recipient_role in recipients:
            if not recipient.active or not recipient.telegram_id:
                delivery_errors.append(recipient.full_name + ": Telegram не подключён")
                continue
            target = student_target if recipient_role == "student" else {"chat_id": recipient.telegram_id}
            if not target:
                delivery_errors.append(recipient.full_name + ": Telegram не подключён")
                continue
            prefix = (
                "От учителя " + sender.full_name + (": " + row.text if row.text else "")
                if principal["role"] == "teacher"
                else "От администратора школы" + (": " + row.text if row.text else "")
            )
            upload = BufferedInputFile(content, filename=original_name)
            kwargs = {**target, "caption": prefix[:1024]}
            try:
                if kind == "photo":
                    sent = await bot.send_photo(photo=upload, **kwargs)
                elif kind == "video":
                    sent = await bot.send_video(video=upload, **kwargs)
                elif kind == "voice":
                    sent = await bot.send_voice(voice=upload, **kwargs)
                elif kind == "audio":
                    sent = await bot.send_audio(audio=upload, **kwargs)
                else:
                    sent = await bot.send_document(document=upload, **kwargs)
                delivered.append({
                    "user_id": recipient.id,
                    "telegram_message_id": sent.message_id,
                    "chat_id": target["chat_id"],
                    "thread_id": target.get("message_thread_id"),
                })
            except Exception as exc:
                logger.warning("Telegram delivery failed for conversation_id=%s: %s", conversation.id, type(exc).__name__)
                delivery_errors.append(recipient.full_name + ": ошибка Telegram (" + type(exc).__name__ + ")")
    else:
        delivery_errors.append("Telegram-бот не подключён к веб-приложению")

    metadata = json.loads(row.metadata_json or "{}")
    metadata["telegram_deliveries"] = delivered
    if delivery_errors:
        metadata["telegram_delivery_errors"] = delivery_errors
    row.metadata_json = json.dumps(metadata, ensure_ascii=False)
    row.delivery_status = "delivered" if delivered and not delivery_errors else ("partial" if delivered else "failed")
    db.commit()

    if bot and teacher.telegram_id:
        try:
            from .telegram_teacher import clear_teacher_session, update_teacher_panel
            current_session = db.get(TeacherSession, teacher.id)
            if current_session and current_session.conversation_id != conversation.id:
                clear_teacher_session(db, teacher)
            await update_teacher_panel(bot, db, teacher)
        except Exception:
            pass
    return _panel_message_dict(row, expose_internal_metadata=(principal["role"] == "admin"))


@router.get("/panel/graph")
def panel_graph(principal: PanelUser, db: Db):
    if principal["role"] != "teacher":
        raise HTTPException(status_code=403, detail="Граф учителя доступен только учителю")
    teacher = db.get(User, principal["user_id"])
    if not teacher or teacher.role != "teacher" or not teacher.active:
        raise HTTPException(status_code=404, detail="Учитель не найден")
    assignments = db.scalars(
        select(Assignment)
        .where(Assignment.teacher_id == teacher.id, Assignment.active.is_(True))
        .order_by(Assignment.created_at.desc())
    ).all()
    students = []
    for assignment in assignments:
        student = assignment.student
        if student and student.active and assignment.conversation and assignment.conversation.status == "active":
            students.append({
                "id": student.id,
                "full_name": student.full_name,
                "role": "student",
                "active": student.active,
            })
    return {
        "teacher": {
            "id": teacher.id,
            "full_name": teacher.full_name,
            "role": "teacher",
            "active": teacher.active,
        },
        "students": students,
        "counts": {"students": len(students)},
    }
