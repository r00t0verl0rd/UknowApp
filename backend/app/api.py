"""HTTP API веб-панели: авторизация, участники, переписки и доставка сообщений."""

import asyncio
import hashlib
import json
import logging
import secrets
import mimetypes
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from aiogram.types import BufferedInputFile
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import selectinload
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .config import ADMIN_USERNAME
from .database import SessionLocal
from .event_hub import publish_chat_update, subscribe_chat_updates, unsubscribe_chat_updates
from .media_storage import MEDIA_DIR, delete_message_media, safe_media_type, media_content_disposition
from .models import Assignment, ConnectionCode, Conversation, Message, PanelSession, PersonalConversation, PersonalMessage, StudentTelegramGroup, TeacherPanel, TeacherSession, User
from .schemas import AssignmentCreate, LoginRequest, PanelMessageCreate, PersonalConversationCreate, PersonalMessageCreate, UserCreate, UserUpdate
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

logger = logging.getLogger(__name__)

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
        "web_username": (user.web_username or user.full_name) if user.role in {"teacher", "student"} else None,
        "role": user.role,
        "telegram_id": user.telegram_id if include_telegram_id else None,
        "active": user.active,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "has_access_code": bool(user.web_password_hash),
    }


def generate_panel_access_code() -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(4)) + "-" + "".join(
        secrets.choice(alphabet) for _ in range(4)
    )


def validate_panel_username(db: Session, username: str, exclude_user_id: Optional[int] = None) -> str:
    cleaned = (username or "").strip()
    if len(cleaned) < 2 or len(cleaned) > 160:
        raise HTTPException(status_code=400, detail="Логин должен содержать от 2 до 160 символов")
    if cleaned.casefold() == ADMIN_USERNAME.casefold():
        raise HTTPException(status_code=409, detail="Этот логин зарезервирован для администратора")
    users = db.scalars(select(User).where(User.role.in_(["teacher", "student"]))).all()
    for user in users:
        if user.id == exclude_user_id:
            continue
        existing = (user.web_username or user.full_name).strip()
        if existing.casefold() == cleaned.casefold():
            raise HTTPException(status_code=409, detail="Этот логин уже используется другим участником")
    return cleaned


def conversation_dicts(
    db: Session,
    conversations: list[Conversation],
    include_telegram_ids: bool = True,
    viewer_role: str = "teacher",
) -> list[dict]:
    if not conversations:
        return []

    conversation_ids = [item.id for item in conversations]
    latest_rank = (
        select(
            Message.id.label("message_id"),
            func.row_number().over(
                partition_by=Message.conversation_id,
                order_by=[Message.created_at.desc(), Message.id.desc()],
            ).label("position"),
        )
        .where(Message.conversation_id.in_(conversation_ids))
        .subquery()
    )
    latest_messages = db.scalars(
        select(Message)
        .join(latest_rank, Message.id == latest_rank.c.message_id)
        .where(latest_rank.c.position == 1)
    ).all()
    latest_by_conversation = {item.conversation_id: item for item in latest_messages}

    if viewer_role == "student":
        unread_condition = and_(
            Message.sender_role.in_(("teacher", "admin")),
            func.json_extract(Message.metadata_json, "$.student_read_at").is_(None),
        )
    elif viewer_role == "admin":
        unread_condition = and_(
            Message.sender_role.in_(("teacher", "student")),
            or_(
                func.json_extract(Message.metadata_json, "$.teacher_read_at").is_(None),
                func.json_extract(Message.metadata_json, "$.student_read_at").is_(None),
            ),
        )
    else:
        unread_condition = and_(
            Message.sender_role.in_(("student", "admin")),
            func.json_extract(Message.metadata_json, "$.teacher_read_at").is_(None),
        )
    statistics = db.execute(
        select(
            Message.conversation_id,
            func.count(Message.id),
            func.coalesce(func.sum(case((unread_condition, 1), else_=0)), 0),
        )
        .where(Message.conversation_id.in_(conversation_ids))
        .group_by(Message.conversation_id)
    ).all()
    stats_by_conversation = {
        conversation_id: (message_count, unread_count)
        for conversation_id, message_count, unread_count in statistics
    }

    result = []
    for conversation in conversations:
        assignment = conversation.assignment
        last_message = latest_by_conversation.get(conversation.id)
        message_count, unread_count = stats_by_conversation.get(conversation.id, (0, 0))
        result.append({
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
            "message_count": message_count,
            "unread_count": unread_count,
        })
    return result


def conversation_dict(
    db: Session, conversation: Conversation, include_telegram_ids: bool = True
) -> dict:
    return conversation_dicts(db, [conversation], include_telegram_ids)[0]


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
        select(Assignment)
        .options(
            selectinload(Assignment.teacher),
            selectinload(Assignment.student),
        )
        .where(Assignment.active.is_(True))
        .order_by(Assignment.created_at.desc())
    ).all()
    active_conversation_count = db.scalar(
        select(func.count(Conversation.id)).where(Conversation.status == "active")
    ) or 0

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
            "conversations": active_conversation_count,
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
    if len(full_name) < 2:
        raise HTTPException(status_code=400, detail="Имя должно содержать минимум два символа")
    has_web_panel = payload.role in {"teacher", "student"}
    web_username = validate_panel_username(db, payload.web_username or full_name) if has_web_panel else None
    issued_access_code = generate_panel_access_code() if has_web_panel else None
    user = User(
        full_name=full_name,
        web_username=web_username,
        role=payload.role,
        telegram_id=payload.telegram_id,
        web_password_hash=hash_web_password(issued_access_code) if issued_access_code else None,
    )
    db.add(user)
    try:
        db.flush()
        if issued_access_code:
            now = datetime.now(timezone.utc)
            db.add(ConnectionCode(
                user_id=user.id,
                code_hash=hashlib.sha256(issued_access_code.replace("-", "").encode("utf-8")).hexdigest(),
                created_at=now,
                expires_at=now + timedelta(days=36500),
            ))
        db.commit()
        db.refresh(user)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Этот Telegram ID уже используется")
    result = user_dict(user)
    if issued_access_code:
        result["issued_access_code"] = issued_access_code
    return result


@router.patch("/admin/users/{user_id}")
def update_user(user_id: int, payload: UserUpdate, _: Admin, db: Db):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    changes = payload.model_dump(exclude_unset=True)
    requested_web_username = changes.pop("web_username", None)
    # Panel access codes are generated server-side and only their hashes are stored.
    target_role = changes.get("role", user.role)
    issued_access_code = None

    has_web_panel = target_role in {"teacher", "student"}
    if has_web_panel:
        previous_username = user.web_username or user.full_name
        if requested_web_username is not None:
            target_username = requested_web_username
        elif "full_name" in changes and previous_username.strip().casefold() == user.full_name.strip().casefold():
            target_username = changes["full_name"].strip()
        else:
            target_username = previous_username
        user.web_username = validate_panel_username(db, target_username, exclude_user_id=user.id)
    else:
        user.web_username = None

    role_changed = "role" in changes and changes["role"] != user.role
    active_access_codes = db.scalars(
        select(ConnectionCode).where(
            ConnectionCode.user_id == user.id,
            ConnectionCode.used_at.is_(None),
        )
    ).all()
    persistent_code_cutoff = datetime.now(timezone.utc) + timedelta(days=365)
    has_active_access_code = any(
        (item.expires_at.replace(tzinfo=timezone.utc) if item.expires_at.tzinfo is None else item.expires_at)
        > persistent_code_cutoff
        for item in active_access_codes
    )
    if has_web_panel and (role_changed or not user.web_password_hash or not has_active_access_code):
        issued_access_code = generate_panel_access_code()
        user.web_password_hash = hash_web_password(issued_access_code)
    elif not has_web_panel:
        user.web_password_hash = None

    if role_changed:
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
            if len(value) < 2:
                raise HTTPException(status_code=400, detail="Имя должно содержать минимум два символа")
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
    if issued_access_code:
        now = datetime.now(timezone.utc)
        db.query(ConnectionCode).filter(
            ConnectionCode.user_id == user.id,
            ConnectionCode.used_at.is_(None),
        ).update({ConnectionCode.used_at: now}, synchronize_session=False)
        db.add(ConnectionCode(
            user_id=user.id,
            code_hash=hashlib.sha256(issued_access_code.replace("-", "").encode("utf-8")).hexdigest(),
            created_at=now,
            expires_at=now + timedelta(days=36500),
        ))
    elif not has_web_panel:
        db.query(ConnectionCode).filter(
            ConnectionCode.user_id == user.id,
            ConnectionCode.used_at.is_(None),
        ).update({ConnectionCode.used_at: datetime.now(timezone.utc)}, synchronize_session=False)
    try:
        db.commit()
        db.refresh(user)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Этот Telegram ID уже используется")
    result = user_dict(user)
    if issued_access_code:
        result["issued_access_code"] = issued_access_code
    return result


@router.post("/admin/users/{user_id}/access-code")
def regenerate_panel_access_code(user_id: int, _: Admin, db: Db):
    user = db.get(User, user_id)
    if not user or user.role not in {"teacher", "student"}:
        raise HTTPException(status_code=404, detail="Участник не найден")
    issued_access_code = generate_panel_access_code()
    user.web_password_hash = hash_web_password(issued_access_code)
    now = datetime.now(timezone.utc)
    db.query(ConnectionCode).filter(
        ConnectionCode.user_id == user.id,
        ConnectionCode.used_at.is_(None),
    ).update({ConnectionCode.used_at: now}, synchronize_session=False)
    db.add(ConnectionCode(
        user_id=user.id,
        code_hash=hashlib.sha256(issued_access_code.replace("-", "").encode("utf-8")).hexdigest(),
        created_at=now,
        expires_at=now + timedelta(days=36500),
    ))
    db.query(PanelSession).filter(
        PanelSession.role == user.role,
        PanelSession.user_id == user.id,
    ).delete(synchronize_session=False)
    db.commit()
    db.refresh(user)
    return {
        **user_dict(user),
        "issued_access_code": issued_access_code,
    }


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

    # Student activation codes are one-time. A teacher's shared access code
    # remains valid after Telegram is disconnected so the teacher can reconnect.
    if user.role == "student":
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

    # Удаляем все служебные ссылки до пользователя: SQLite теперь проверяет внешние ключи.
    db.query(PanelSession).filter(PanelSession.user_id == user.id).delete(synchronize_session=False)
    db.query(StudentTelegramGroup).filter(
        StudentTelegramGroup.student_id == user.id
    ).delete(synchronize_session=False)
    db.query(TeacherSession).filter(
        TeacherSession.teacher_id == user.id
    ).delete(synchronize_session=False)
    db.query(TeacherPanel).filter(TeacherPanel.teacher_id == user.id).delete(synchronize_session=False)
    if assignments:
        db.query(Assignment).filter(
            Assignment.id.in_([item.id for item in assignments])
        ).delete(synchronize_session=False)
    personal_chat = db.scalar(select(PersonalConversation).where(PersonalConversation.participant_id == user.id))
    if personal_chat:
        db.query(PersonalMessage).filter(PersonalMessage.conversation_id == personal_chat.id).delete(synchronize_session=False)
        db.delete(personal_chat)
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
    if user.role in {"teacher", "student"}:
        # Both panel roles use the same persistent code for web login and Telegram.
        access_code = generate_panel_access_code()
        user.web_password_hash = hash_web_password(access_code)
        db.query(PanelSession).filter(
            PanelSession.role == user.role,
            PanelSession.user_id == user.id,
        ).delete(synchronize_session=False)
        now = datetime.now(timezone.utc)
        db.query(ConnectionCode).filter(
            ConnectionCode.user_id == user.id,
            ConnectionCode.used_at.is_(None),
        ).update({ConnectionCode.used_at: now}, synchronize_session=False)
        db.add(ConnectionCode(
            user_id=user.id,
            code_hash=hashlib.sha256(access_code.replace("-", "").encode("utf-8")).hexdigest(),
            created_at=now,
            expires_at=now + timedelta(days=36500),
        ))
        db.commit()
        db.refresh(user)
        return {
            "code": access_code,
            "expires_at": None,
            "lifetime_minutes": None,
            "user": user.full_name,
            "role": user.role,
            "shared_access": True,
        }

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
    # Student codes do not expire while unused; they are consumed on first activation.
    expires_at = now + timedelta(days=36500)

    db.add(ConnectionCode(
        user_id=user.id,
        code_hash=code_hash,
        created_at=now,
        expires_at=expires_at,
    ))
    db.commit()

    return {
        "code": raw_code[:4] + "-" + raw_code[4:],
        "expires_at": None,
        "lifetime_minutes": None,
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
    publish_chat_update(conversation.id)
    return conversation_dict(db, conversation)


def _panel_visible_conversation(db: Session, principal: dict, conversation_id: int) -> Conversation:
    # Проверяем доступ к диалогу на сервере, даже если клиент подменит его ID.
    conversation = db.get(Conversation, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Переписка не найдена")
    if principal["role"] in {"teacher", "student"}:
        assignment = conversation.assignment
        participant_id = (
            assignment.teacher_id if principal["role"] == "teacher" else assignment.student_id
        )
        if (
            participant_id != principal["user_id"]
            or not assignment.active
            or not assignment.teacher.active
            or not assignment.student.active
            or conversation.status != "active"
        ):
            raise HTTPException(status_code=404, detail="Переписка не найдена")
        if principal["role"] == "student":
            current_conversation_id = db.scalar(
                select(Conversation.id)
                .join(Assignment, Conversation.assignment_id == Assignment.id)
                .join(User, Assignment.teacher_id == User.id)
                .where(
                    Assignment.student_id == principal["user_id"],
                    Assignment.active.is_(True),
                    User.active.is_(True),
                    Conversation.status == "active",
                )
                .order_by(Conversation.created_at.desc(), Conversation.id.desc())
                .limit(1)
            )
            if current_conversation_id != conversation.id:
                raise HTTPException(status_code=404, detail="Переписка не найдена")
    return conversation


def _panel_message_dict(
    item: Message,
    expose_internal_metadata: bool = True,
    principal: Optional[dict] = None,
) -> dict:
    # Внутренние Telegram ID и file_id не раскрываем учителю в обычном ответе API.
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
        "can_delete": bool(
            principal
            and item.sender_role == principal["role"]
            and (
                principal["role"] == "admin"
                or item.sender_id == principal.get("user_id")
            )
        ),
        "content_type": item.content_type,
        "text": item.text,
        "metadata": metadata,
        "delivery_status": item.delivery_status,
        "panel_read_at": (
            metadata.get("student_read_at") if item.sender_role == "teacher"
            else metadata.get("teacher_read_at") if item.sender_role == "student"
            else (
                metadata.get("teacher_read_at") and metadata.get("student_read_at")
                if item.sender_role == "admin" else None
            )
        ),
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

    # If the conversation has no usable recent delivery route yet, fall back
    # to the student's current verified forum-topic binding instead of always
    # sending the first teacher-initiated message to the private bot chat.
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
        or not user.active
        or user.role != principal["role"]
        or user.role not in {"teacher", "student"}
    ):
        raise HTTPException(status_code=401, detail="Учётная запись недоступна")
    return {"role": user.role, "id": user.id, "full_name": user.full_name}


@router.get("/panel/events")
async def panel_events(request: Request, principal: PanelUser):
    """Keep an authenticated browser connection open for conversation changes."""

    async def event_stream():
        queue = subscribe_chat_updates()
        try:
            # The initial event makes the client perform one authoritative load
            # after the stream is established, so no polling timer is necessary.
            yield "retry: 5000\n\n"
            yield "event: update\ndata: {}\n\n"
            while not await request.is_disconnected():
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=20)
                except asyncio.TimeoutError:
                    # SSE comment frames keep intermediaries from closing an idle
                    # connection; they do not trigger a browser data callback.
                    yield ": keep-alive\n\n"
                    continue
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
            selectinload(Conversation.assignment).selectinload(Assignment.teacher),
            selectinload(Conversation.assignment).selectinload(Assignment.student),
        )
        .join(Assignment, Conversation.assignment_id == Assignment.id)
        .join(User, Assignment.student_id == User.id)
        .where(
            Assignment.active.is_(True),
            User.active.is_(True),
            Assignment.teacher.has(User.active.is_(True)),
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


def _personal_conversation(db: Session, principal: dict, conversation_id: int) -> PersonalConversation:
    conversation = db.get(PersonalConversation, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Личный диалог не найден")
    if principal["role"] != "admin" and conversation.participant_id != principal.get("user_id"):
        raise HTTPException(status_code=404, detail="Личный диалог не найден")
    return conversation


def _personal_conversation_dict(item: PersonalConversation, viewer_role: str, unread_count: int = 0) -> dict:
    participant = item.participant
    return {
        "id": item.id,
        "type": "personal",
        "participant": {"id": participant.id, "full_name": participant.full_name, "role": participant.role},
        "title": participant.full_name if viewer_role == "admin" else "Администратор",
        "created_at": item.created_at.isoformat(),
        "unread_count": unread_count,
    }


@router.get("/panel/personal-conversations")
def personal_conversations(principal: PanelUser, db: Db):
    statement = select(PersonalConversation).options(
        selectinload(PersonalConversation.participant)
    ).order_by(PersonalConversation.created_at.desc(), PersonalConversation.id.desc())
    if principal["role"] != "admin":
        statement = statement.where(PersonalConversation.participant_id == principal["user_id"])
    result = []
    read_column = PersonalMessage.admin_read_at if principal["role"] == "admin" else PersonalMessage.participant_read_at
    for item in db.scalars(statement).all():
        unread_count = db.scalar(select(func.count(PersonalMessage.id)).where(PersonalMessage.conversation_id == item.id, PersonalMessage.sender_role != principal["role"], read_column.is_(None))) or 0
        result.append(_personal_conversation_dict(item, principal["role"], unread_count))
    return result


@router.post("/panel/personal-conversations", status_code=201)
def create_personal_conversation(payload: PersonalConversationCreate, principal: PanelUser, db: Db):
    if principal["role"] != "admin":
        raise HTTPException(status_code=403, detail="Создавать личные диалоги может только администратор")
    participant = db.get(User, payload.user_id)
    if not participant or participant.role not in {"teacher", "student"} or not participant.active:
        raise HTTPException(status_code=404, detail="Активный участник не найден")
    item = db.scalar(select(PersonalConversation).where(PersonalConversation.participant_id == participant.id))
    if not item:
        item = PersonalConversation(participant_id=participant.id)
        db.add(item)
        db.commit()
        db.refresh(item)
    publish_chat_update(0)
    return _personal_conversation_dict(item, principal["role"])


@router.get("/panel/personal-conversations/{conversation_id}/messages")
def personal_messages(conversation_id: int, principal: PanelUser, db: Db):
    item = _personal_conversation(db, principal, conversation_id)
    read_column = PersonalMessage.admin_read_at if principal["role"] == "admin" else PersonalMessage.participant_read_at
    incoming = db.scalars(select(PersonalMessage).where(PersonalMessage.conversation_id == item.id, PersonalMessage.sender_role != principal["role"], read_column.is_(None))).all()
    if incoming:
        now = datetime.now(timezone.utc)
        for message in incoming:
            setattr(message, "admin_read_at" if principal["role"] == "admin" else "participant_read_at", now)
        db.commit()
        publish_chat_update(0)
    rows = db.scalars(
        select(PersonalMessage).where(PersonalMessage.conversation_id == item.id)
        .order_by(PersonalMessage.created_at, PersonalMessage.id)
    ).all()
    return [{
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
        "created_at": row.created_at.isoformat(),
    } for row in rows]


@router.post("/panel/personal-conversations/{conversation_id}/messages", status_code=201)
def send_personal_message(
    conversation_id: int,
    payload: PersonalMessageCreate,
    principal: PanelUser,
    db: Db,
):
    item = _personal_conversation(db, principal, conversation_id)
    if principal["role"] not in {"admin", "teacher", "student"}:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    if principal["role"] == "admin":
        sender_id = None
    else:
        sender = db.get(User, principal["user_id"])
        if not sender or not sender.active or sender.id != item.participant_id:
            raise HTTPException(status_code=403, detail="Нет доступа к личному диалогу")
        sender_id = sender.id
    row = PersonalMessage(
        conversation_id=item.id,
        sender_id=sender_id,
        sender_role=principal["role"],
        text=payload.text.strip(),
    )
    if not row.text:
        raise HTTPException(status_code=400, detail="Введите сообщение")
    db.add(row)
    db.commit()
    db.refresh(row)
    publish_chat_update(0)
    return {
        "id": row.id,
        "sender": row.sender.full_name if row.sender else "Администратор",
        "sender_role": row.sender_role,
        "can_delete": True,
        "content_type": "text",
        "text": row.text,
        "metadata": {},
        "delivery_status": "delivered",
        "created_at": row.created_at.isoformat(),
    }


@router.delete("/panel/personal-messages/{message_id}")
def delete_personal_message(message_id: int, principal: PanelUser, db: Db):
    row = db.get(PersonalMessage, message_id)
    if not row:
        raise HTTPException(status_code=404, detail="Сообщение не найдено")
    _personal_conversation(db, principal, row.conversation_id)
    if row.sender_role != principal["role"] or (
        principal["role"] != "admin" and row.sender_id != principal.get("user_id")
    ):
        raise HTTPException(status_code=403, detail="Можно удалить только собственное сообщение")
    db.delete(row)
    db.commit()
    publish_chat_update(0)
    return {"ok": True, "deleted_message_id": message_id}


@router.get("/panel/conversations/{conversation_id}/messages")
def panel_messages(conversation_id: int, principal: PanelUser, db: Db):
    conversation = _panel_visible_conversation(db, principal, conversation_id)
    rows = db.scalars(
        select(Message).where(Message.conversation_id == conversation.id)
        .order_by(Message.created_at, Message.id)
    ).all()
    if principal["role"] in {"teacher", "student"}:
        read_key = "teacher_read_at" if principal["role"] == "teacher" else "student_read_at"
        sender_roles = {"student", "admin"} if principal["role"] == "teacher" else {"teacher", "admin"}
        now = datetime.now(timezone.utc).isoformat()
        changed = False
        for row in rows:
            if row.sender_role not in sender_roles:
                continue
            metadata = json.loads(row.metadata_json or "{}")
            if metadata.get(read_key) is None:
                metadata[read_key] = now
                row.metadata_json = json.dumps(metadata, ensure_ascii=False)
                changed = True
        if changed:
            db.commit()
            publish_chat_update(conversation.id)
    return [
        _panel_message_dict(
            item,
            expose_internal_metadata=(principal["role"] == "admin"),
            principal=principal,
        )
        for item in rows
    ]


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
    deliveries = metadata.get("telegram_deliveries") or []
    bot = getattr(request.app.state, "telegram_bot", None)
    telegram_deleted = 0
    telegram_failed = 0

    # Remove every Telegram copy recorded at delivery time. Telegram may reject
    # deletion of old messages or messages that are no longer accessible; the
    # web history is still removed and the response reports those failures.
    if deliveries and bot:
        for delivery in deliveries:
            try:
                chat_id = int(delivery["chat_id"])
                telegram_message_id = int(delivery["telegram_message_id"])
                await bot.delete_message(
                    chat_id=chat_id,
                    message_id=telegram_message_id,
                )
                telegram_deleted += 1
            except Exception as exc:
                telegram_failed += 1
                logger.warning(
                    "Could not delete Telegram copy (message_id=%s error_type=%s)",
                    item.id,
                    type(exc).__name__,
                )
    else:
        telegram_failed = len(deliveries)

    delete_message_media(item.metadata_json)
    db.delete(item)
    db.commit()
    publish_chat_update(conversation.id)

    return {
        "ok": True,
        "deleted_message_id": message_id,
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
    """Resolve the sender and Telegram recipients for a panel message."""
    student = conversation.assignment.student
    teacher = conversation.assignment.teacher
    if principal["role"] == "teacher":
        sender = teacher
        recipients = [(student, "student")]
    elif principal["role"] == "student":
        sender = student
        recipients = [(teacher, "teacher")]
    else:
        sender = db.scalar(select(User).where(User.role == "admin").order_by(User.id).limit(1))
        if not sender:
            sender = User(full_name="Администратор", role="admin", active=True)
            db.add(sender)
            db.flush()
        recipients = [(student, "student"), (teacher, "teacher")]
    if not sender:
        raise HTTPException(status_code=401, detail="Учётная запись недоступна")
    return sender, recipients, student, teacher


def _save_panel_delivery_result(db: Session, row: Message, conversation: Conversation, delivered: list[dict], delivery_errors: list[dict]) -> None:
    metadata = json.loads(row.metadata_json or "{}")
    metadata["telegram_deliveries"] = delivered
    if delivery_errors:
        metadata["telegram_delivery_errors"] = delivery_errors
    row.metadata_json = json.dumps(metadata, ensure_ascii=False)
    row.delivery_status = (
        "delivered" if (delivered or row.sender_role == "teacher") and not delivery_errors
        else ("partial" if delivered else "failed")
    )
    db.commit()
    publish_chat_update(conversation.id)


async def _store_panel_attachment(request: Request, file: UploadFile, conversation_id: int):
    """Validate and persist an uploaded attachment; return normalized metadata."""
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
    target_path.write_bytes(content)

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
    return content, original_name, relative, mime_type, kind


async def _refresh_teacher_panel_after_web_delivery(bot, db: Session, teacher: User, conversation: Conversation) -> None:
    """Refresh the teacher's Telegram panel after a web message has been persisted."""
    if not bot or not teacher.telegram_id:
        return
    try:
        from .telegram_teacher import clear_teacher_session, update_teacher_panel
        current_session = db.get(TeacherSession, teacher.id)
        if current_session and current_session.conversation_id != conversation.id:
            clear_teacher_session(db, teacher)
        await update_teacher_panel(bot, db, teacher)
    except Exception as exc:
        # Delivery is already committed; a panel refresh failure must not undo it.
        logger.warning(
            "Could not refresh teacher panel after web delivery "
            "(teacher_id=%s conversation_id=%s error_type=%s)",
            teacher.id, conversation.id, type(exc).__name__,
        )


@router.post("/panel/conversations/{conversation_id}/messages", status_code=201)
async def send_panel_message(
    conversation_id: int,
    payload: PanelMessageCreate,
    request: Request,
    principal: PanelUser,
    db: Db,
):
    # Сначала сохраняем сообщение в БД, затем отправляем его адресатам в Telegram.
    conversation = _panel_visible_conversation(db, principal, conversation_id)
    body = payload.text.strip()
    if text_contains_contact_data(body):
        raise HTTPException(status_code=400, detail="Контактные данные нельзя отправлять через чат UknowApp")
    if not body:
        raise HTTPException(status_code=400, detail="Введите текст сообщения")

    sender, recipients, student, teacher = _panel_sender_and_recipients(db, principal, conversation)

    rows = db.scalars(
        select(Message).where(Message.conversation_id == conversation.id)
        .order_by(Message.created_at, Message.id)
    ).all()
    student_target = (
        _panel_student_telegram_target(db, conversation, rows)
        if any(role == "student" for _, role in recipients) else None
    )

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
            if not recipient.active:
                delivery_errors.append({"name": recipient.full_name, "role": recipient_role, "reason": "Telegram не подключён"})
                continue
            if not recipient.telegram_id:
                if not (principal["role"] == "teacher" and recipient_role == "student"):
                    delivery_errors.append({"name": recipient.full_name, "role": recipient_role, "reason": "Telegram не подключён"})
                continue
            try:
                target = student_target if recipient_role == "student" else {"chat_id": recipient.telegram_id}
                if not target:
                    if not (principal["role"] == "teacher" and recipient_role == "student"):
                        delivery_errors.append({"name": recipient.full_name, "role": recipient_role, "reason": "Telegram не подключён"})
                    continue
                # The student already knows this is the teacher's private chat.
                # Deliver teacher text naturally; only label a separate admin role.
                outgoing_text = (
                    body if principal["role"] == "teacher"
                    else "Сообщение от ученика " + student.full_name + ":\n" + body
                    if principal["role"] == "student"
                    else "Сообщение от администратора школы:\n" + body
                )
                sent = await bot.send_message(**target, text=outgoing_text)
                delivered.append({
                    "user_id": recipient.id,
                    "telegram_message_id": sent.message_id,
                    "chat_id": target["chat_id"],
                    "thread_id": target.get("message_thread_id"),
                })
            except Exception as exc:
                logger.warning("Telegram delivery failed for conversation_id=%s: %s", conversation.id, type(exc).__name__)
                delivery_errors.append({"name": recipient.full_name, "role": recipient_role, "reason": "ошибка Telegram (" + type(exc).__name__ + ")"})
    else:
        delivery_errors.append({"name": "", "role": "", "reason": "Telegram-бот не подключён к веб-приложению"})

    _save_panel_delivery_result(db, row, conversation, delivered, delivery_errors)

    await _refresh_teacher_panel_after_web_delivery(bot, db, teacher, conversation)

    return _panel_message_dict(row, expose_internal_metadata=(principal["role"] == "admin"), principal=principal)


@router.post("/panel/conversations/{conversation_id}/attachments", status_code=201)
async def send_panel_attachment(
    conversation_id: int,
    request: Request,
    principal: PanelUser,
    db: Db,
    file: UploadFile = File(...),
    text: str = Form(default=""),
):
    # Ограничиваем размер до чтения файла целиком и сохраняем локальную копию для веб-панели.
    conversation = _panel_visible_conversation(db, principal, conversation_id)
    if len(text or "") > 3900:
        raise HTTPException(status_code=400, detail="Текст к вложению слишком длинный")
    sender, recipients, student, teacher = _panel_sender_and_recipients(db, principal, conversation)

    if text_contains_contact_data((text or "").strip()):
        raise HTTPException(status_code=400, detail="Контактные данные нельзя отправлять через чат UknowApp")
    content, original_name, relative, mime_type, kind = await _store_panel_attachment(
        request, file, conversation.id
    )

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
    student_target = (
        _panel_student_telegram_target(db, conversation, rows[:-1])
        if any(role == "student" for _, role in recipients) else None
    )

    bot = getattr(request.app.state, "telegram_bot", None)
    delivery_errors = []
    delivered = []
    if bot:
        for recipient, recipient_role in recipients:
            if not recipient.active:
                delivery_errors.append({"name": recipient.full_name, "role": recipient_role, "reason": "Telegram не подключён"})
                continue
            if not recipient.telegram_id:
                if not (principal["role"] == "teacher" and recipient_role == "student"):
                    delivery_errors.append({"name": recipient.full_name, "role": recipient_role, "reason": "Telegram не подключён"})
                continue
            target = student_target if recipient_role == "student" else {"chat_id": recipient.telegram_id}
            if not target:
                if not (principal["role"] == "teacher" and recipient_role == "student"):
                    delivery_errors.append({"name": recipient.full_name, "role": recipient_role, "reason": "Telegram не подключён"})
                continue
            # Teacher and student already share this conversation; avoid repeating
            # a sender label on every teacher attachment.
            caption = (
                (row.text or "").strip()[:1024]
                if principal["role"] == "teacher"
                else (
                    "Сообщение от ученика " + student.full_name
                    + ((": " + row.text) if row.text else "")
                    if principal["role"] == "student"
                    else ("От администратора школы" + ((": " + row.text) if row.text else ""))
                )
            )
            kwargs = {**target}
            if caption:
                kwargs["caption"] = caption
            try:
                upload = BufferedInputFile(content, filename=original_name)
                if kind == "photo" and len(content) <= 10 * 1024 * 1024:
                    sent = await bot.send_photo(photo=upload, **kwargs)
                elif kind == "animation":
                    sent = await bot.send_animation(animation=upload, **kwargs)
                elif kind == "video":
                    sent = await bot.send_video(video=upload, **kwargs)
                elif kind == "voice":
                    sent = await bot.send_voice(voice=upload, **kwargs)
                elif kind == "audio":
                    sent = await bot.send_audio(audio=upload, **kwargs)
                else:
                    sent = await bot.send_document(
                        document=BufferedInputFile(content, filename=original_name),
                        **kwargs,
                    )
                delivered.append({
                    "user_id": recipient.id,
                    "telegram_message_id": sent.message_id,
                    "chat_id": target["chat_id"],
                    "thread_id": target.get("message_thread_id"),
                })
            except Exception as native_exc:
                # Photos above Telegram's photo limit, uncommon codecs and media
                # rejected by a native endpoint should still arrive as files.
                try:
                    logger.info(
                        "Native Telegram media send failed; retrying as document "
                        "(conversation_id=%s kind=%s error_type=%s)",
                        conversation.id, kind, type(native_exc).__name__,
                    )
                    sent = await bot.send_document(
                        document=BufferedInputFile(content, filename=original_name),
                        **kwargs,
                    )
                    delivered.append({
                        "user_id": recipient.id,
                        "telegram_message_id": sent.message_id,
                        "chat_id": target["chat_id"],
                        "thread_id": target.get("message_thread_id"),
                    })
                except Exception as exc:
                    logger.warning("Telegram delivery failed for conversation_id=%s: %s", conversation.id, type(exc).__name__)
                    delivery_errors.append({"name": recipient.full_name, "role": recipient_role, "reason": "ошибка Telegram (" + type(exc).__name__ + ")"})
    else:
        delivery_errors.append({"name": "", "role": "", "reason": "Telegram-бот не подключён к веб-приложению"})

    _save_panel_delivery_result(db, row, conversation, delivered, delivery_errors)

    await _refresh_teacher_panel_after_web_delivery(bot, db, teacher, conversation)
    return _panel_message_dict(row, expose_internal_metadata=(principal["role"] == "admin"), principal=principal)


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
