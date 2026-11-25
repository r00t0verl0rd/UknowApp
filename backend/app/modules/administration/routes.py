"""API управления пользователями и назначениями."""

import hashlib
import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app.core.security import hash_web_password
from app.infrastructure.storage.media import delete_message_media
from app.models import (
    Assignment,
    ConnectionCode,
    Conversation,
    Message,
    PanelSession,
    PersonalConversation,
    PersonalMessage,
    User,
)
from app.modules.assignments.service import assign_student, unassign_student
from app.modules.communication.accounts import (
    MessengerAccountConflict,
    delete_user_messenger_accounts,
    get_messenger_account,
    sync_messenger_account,
)
from app.modules.dependencies import Db, SchoolStructure, UserManagement
from app.modules.users.service import (
    generate_panel_access_code,
    user_dict,
    validate_panel_username,
)
from app.request_validation import (
    assignment_payload,
    user_create_payload,
    user_update_payload,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

@router.get("/admin/overview")
def overview(_: SchoolStructure, db: Db):
    users = db.scalars(select(User).options(selectinload(User.messenger_accounts)).order_by(User.full_name)).all()
    assignments = db.scalars(
        select(Assignment)
        .options(
            selectinload(Assignment.teacher),
            selectinload(Assignment.student),
        )
        .where(Assignment.active.is_(True))
        .order_by(Assignment.created_at.desc()),
    ).all()
    active_conversation_count = db.scalar(
        select(func.count(Conversation.id)).where(Conversation.status == "active"),
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
def list_users(_: UserManagement, db: Db):
    users = db.scalars(select(User).options(selectinload(User.messenger_accounts)).where(User.role.in_(["teacher", "student"])).order_by(User.role, User.full_name)).all()
    return [user_dict(user, include_additional_info=True) for user in users]


@router.post("/admin/users", status_code=201)
def create_user(payload: dict, _: UserManagement, db: Db):
    payload = user_create_payload(payload)
    full_name = payload["full_name"].strip()
    if len(full_name) < 2:
        raise HTTPException(status_code=400, detail="Имя должно содержать минимум два символа")
    has_web_panel = payload.get("role") in {"teacher", "student"}
    web_username = validate_panel_username(db, payload.get("web_username") or full_name) if has_web_panel else None
    issued_access_code = generate_panel_access_code() if has_web_panel else None
    user = User(
        full_name=full_name,
        additional_info=((payload.get("additional_info") or "").strip() or None) if payload.get("role") == "student" else None,
        web_username=web_username,
        role=payload.get("role"),
        web_password_hash=hash_web_password(issued_access_code) if issued_access_code else None,
    )
    db.add(user)
    try:
        db.flush()
        if payload.get("messenger_account"):
            account = payload["messenger_account"]
            sync_messenger_account(db, user.id, account["platform"], account["external_user_id"])
        if issued_access_code:
            now = datetime.now(UTC)
            db.add(ConnectionCode(
                user_id=user.id,
                code_hash=hashlib.sha256(issued_access_code.replace("-", "").encode("utf-8")).hexdigest(),
                created_at=now,
                expires_at=now + timedelta(days=36500),
            ))
        db.commit()
        db.refresh(user)
    except (IntegrityError, MessengerAccountConflict) as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Этот аккаунт мессенджера уже используется") from exc
    result = user_dict(user)
    if issued_access_code:
        result["issued_access_code"] = issued_access_code
    return result


@router.patch("/admin/users/{user_id}")
def update_user(user_id: int, payload: dict, _: UserManagement, db: Db):
    payload = user_update_payload(payload)
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    changes = payload
    account = changes.pop("messenger_account", None)
    requested_web_username = changes.pop("web_username", None)
    # Создаём коды на сервере, в БД храним хеши.
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
    if has_web_panel and not user.web_password_hash:
        issued_access_code = generate_panel_access_code()
        user.web_password_hash = hash_web_password(issued_access_code)
    elif not has_web_panel:
        user.web_password_hash = None

    if role_changed:
        assignments = db.scalars(select(Assignment).where(Assignment.active.is_(True), (Assignment.teacher_id == user.id) | (Assignment.student_id == user.id))).all()
        now = datetime.now(UTC)
        for assignment in assignments:
            assignment.active = False
            assignment.closed_at = now
            if assignment.conversation:
                assignment.conversation.status = "closed"
    if target_role != "student":
        user.additional_info = None
    for field, value in changes.items():
        if field == "additional_info":
            value = ((value or "").strip() or None) if target_role == "student" else None
        if field == "full_name" and value is not None:
            value = value.strip()
            if len(value) < 2:
                raise HTTPException(status_code=400, detail="Имя должно содержать минимум два символа")
        setattr(user, field, value)
    if issued_access_code:
        now = datetime.now(UTC)
        db.query(ConnectionCode).filter(ConnectionCode.user_id == user.id).delete(synchronize_session=False)
        db.add(ConnectionCode(
            user_id=user.id,
            code_hash=hashlib.sha256(issued_access_code.replace("-", "").encode("utf-8")).hexdigest(),
            created_at=now,
            expires_at=now + timedelta(days=36500),
        ))
    elif not has_web_panel:
        db.query(ConnectionCode).filter(ConnectionCode.user_id == user.id).delete(synchronize_session=False)
    try:
        if account is not None:
            sync_messenger_account(db, user.id, account["platform"], account["external_user_id"])
        db.commit()
        db.refresh(user)
    except (MessengerAccountConflict, IntegrityError) as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Этот аккаунт мессенджера уже используется") from exc
    result = user_dict(user)
    if issued_access_code:
        result["issued_access_code"] = issued_access_code
    return result


@router.post("/admin/users/{user_id}/access-code")
def regenerate_panel_access_code(user_id: int, _: UserManagement, db: Db):
    user = db.get(User, user_id)
    if not user or user.role not in {"teacher", "student"}:
        raise HTTPException(status_code=404, detail="Участник не найден")
    issued_access_code = generate_panel_access_code()
    user.web_password_hash = hash_web_password(issued_access_code)
    now = datetime.now(UTC)
    db.query(ConnectionCode).filter(ConnectionCode.user_id == user.id).delete(synchronize_session=False)
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


@router.post("/admin/users/{user_id}/messengers/{platform}/disconnect")
def disconnect_messenger(user_id: int, platform: str, _: UserManagement, db: Db):
    user = db.get(User, user_id)
    if not user or user.role not in {"teacher", "student"}:
        raise HTTPException(status_code=404, detail="Учитель или ученик не найден")
    account = get_messenger_account(db, user_id, platform)
    if account is None:
        raise HTTPException(status_code=409, detail="Мессенджер уже отключён")
    external_id = account.external_user_id
    sync_messenger_account(db, user.id, platform, None)
    db.commit()
    db.refresh(user)
    return {"ok": True, "user": user_dict(user), "disconnected_external_user_id": external_id}


@router.delete("/admin/users/{user_id}")
def delete_user(user_id: int, _: UserManagement, db: Db):
    user = db.get(User, user_id)
    if not user or user.role not in {"teacher", "student"}:
        raise HTTPException(status_code=404, detail="Учитель или ученик не найден")

    assignments = db.scalars(
        select(Assignment).where(
            (Assignment.teacher_id == user.id) | (Assignment.student_id == user.id),
        ),
    ).all()
    conversation_ids = set(db.scalars(
        select(Conversation.id).where(
            (Conversation.teacher_id == user.id) | (Conversation.student_id == user.id),
        ),
    ).all())
    conversation_ids.update(item.conversation.id for item in assignments if item.conversation)
    conversation_ids = list(conversation_ids)
    if conversation_ids:
        media_rows = db.scalars(select(Message).where(Message.conversation_id.in_(conversation_ids))).all()
        for media_row in media_rows:
            delete_message_media(media_row.metadata_json)
        db.query(Message).filter(
            Message.conversation_id.in_(conversation_ids),
        ).delete(synchronize_session=False)
        db.query(Conversation).filter(
            Conversation.id.in_(conversation_ids),
        ).delete(synchronize_session=False)

    # Удаляем все служебные ссылки до пользователя: SQLite теперь проверяет внешние ключи.
    db.query(PanelSession).filter(PanelSession.user_id == user.id).delete(synchronize_session=False)
    if assignments:
        db.query(Assignment).filter(
            Assignment.id.in_([item.id for item in assignments]),
        ).delete(synchronize_session=False)
    personal_chat = db.scalar(select(PersonalConversation).where(PersonalConversation.participant_id == user.id))
    if personal_chat:
        db.query(PersonalMessage).filter(PersonalMessage.conversation_id == personal_chat.id).delete(synchronize_session=False)
        db.delete(personal_chat)
    db.query(ConnectionCode).filter(
        ConnectionCode.user_id == user.id,
    ).delete(synchronize_session=False)
    delete_user_messenger_accounts(db, user.id)
    db.delete(user)
    db.commit()
    return {"ok": True, "deleted_user_id": user_id, "deleted_conversations": len(conversation_ids)}


@router.post("/admin/users/{user_id}/connection-code")
def generate_connection_code(user_id: int, _: UserManagement, db: Db):
    user = db.get(User, user_id)
    if not user or user.role not in {"teacher", "student"}:
        raise HTTPException(status_code=404, detail="Учитель или ученик не найден")

    access_code = generate_panel_access_code()
    user.web_password_hash = hash_web_password(access_code)
    db.query(PanelSession).filter(
        PanelSession.role == user.role,
        PanelSession.user_id == user.id,
    ).delete(synchronize_session=False)

    now = datetime.now(UTC)
    db.query(ConnectionCode).filter(ConnectionCode.user_id == user.id).delete(synchronize_session=False)
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
        "username": user.web_username or user.full_name,
        "expires_at": None,
        "lifetime_minutes": None,
        "user": user.full_name,
        "role": user.role,
        "shared_access": True,
    }

@router.post("/admin/assignments", status_code=201)
def assign_student_route(payload: dict, _: SchoolStructure, db: Db):
    return assign_student(assignment_payload(payload), db)


@router.delete("/admin/assignments/{student_id}")
def unassign_student_route(student_id: int, _: SchoolStructure, db: Db):
    return unassign_student(student_id, db)



from app.modules.administration.data import router as admin_data_router

router.include_router(admin_data_router)
