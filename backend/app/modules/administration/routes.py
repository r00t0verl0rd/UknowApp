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

from ...config import ADMIN_USERNAME, VAPID_PUBLIC_KEY
from ...event_hub import publish_chat_update, subscribe_chat_updates, unsubscribe_chat_updates
from ...modules.media.service import MEDIA_DIR, delete_message_media, safe_media_type, media_content_disposition
from ...models import Assignment, ConnectionCode, Conversation, Message, PanelSession, PersonalConversation, PersonalMessage, StudentTelegramGroup, TeacherPanel, TeacherSession, User, PushSubscription
from ...schemas import AssignmentCreate, LoginRequest, PanelMessageCreate, PersonalConversationCreate, PersonalMessageCreate, UserCreate, UserUpdate
from ...security import (
    authenticate_panel_user,
    check_login_rate_limit,
    clear_panel_cookies,
    clear_username_failures,
    create_panel_session,
    hash_web_password,
    record_failed_login,
    revoke_panel_session,
    verify_request_origin,
)
from ...telegram_common import text_contains_contact_data
from ...push_notifications import schedule_push
from .modules.users.service import user_dict, generate_panel_access_code, validate_panel_username
from .modules.conversations.service import conversation_dict, conversation_dicts
from .modules.personal_chat.service import _personal_conversation, _personal_conversation_dict
from .modules.assignments.service import assign_student
from .modules.messaging.service import _panel_visible_conversation, _panel_message_dict

from ..dependencies import Admin, PanelUser, Db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

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
        students_by_teacher.setdefault(assignment.teacher_id, []).append(user_dict(assignment.student, include_additional_info=True))

    teachers = []
    for user in users:
        if user.role != "teacher":
            continue
        teachers.append({**user_dict(user), "students": students_by_teacher.get(user.id, [])})

    return {
        "admin": {"label": "Администратор", "role": "admin"},
        "counts": {
            "teachers": sum(1 for user in users if user.role == "teacher"),
            "students": sum(1 for user in users if user.role == "student"),
            "assignments": len(assignments),
            "conversations": active_conversation_count,
            "messages": db.query(Message).count(),
        },
        "teachers": teachers,
    }


@router.get("/admin/users")
def list_users(_: Admin, db: Db):
    users = db.scalars(select(User).where(User.role.in_(["teacher", "student"])).order_by(User.role, User.full_name)).all()
    return [user_dict(user, include_additional_info=True) for user in users]


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
        additional_info=((payload.additional_info or '').strip() or None) if payload.role == 'student' else None,
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
    if target_role != "student":
        user.additional_info = None
    for field, value in changes.items():
        if field == "additional_info":
            value = ((value or '').strip() or None) if target_role == 'student' else None
        if field == "full_name" and value is not None:
            value = value.strip()
            if len(value) < 2:
                raise HTTPException(status_code=400, detail="Имя должно содержать минимум два символа")
        setattr(user, field, value)
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
    conversation_ids = set(db.scalars(
        select(Conversation.id).where(
            (Conversation.teacher_id == user.id) | (Conversation.student_id == user.id)
        )
    ).all())
    conversation_ids.update(item.conversation.id for item in assignments if item.conversation)
    conversation_ids = list(conversation_ids)
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
def assign_student_route(payload: AssignmentCreate, _: Admin, db: Db):
    return assign_student(payload, db)



from ...admin_data import router as admin_data_router
router.include_router(admin_data_router)
