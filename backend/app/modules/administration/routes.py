"""HTTP API веб-панели: авторизация, участники, переписки и доставка сообщений."""

import hashlib
import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app.models import (
    Assignment,
    ConnectionCode,
    Conversation,
    GraphPosition,
    Message,
    PanelSession,
    PersonalConversation,
    PersonalMessage,
    StudentTelegramGroup,
    TeacherPanel,
    TeacherSession,
    User,
)
from app.modules.assignments.service import assign_student, unassign_student
from app.modules.communication.accounts import (
    MessengerAccountConflict,
    delete_user_messenger_accounts,
    sync_messenger_account,
)
from app.modules.communication.contracts import MessengerPlatform
from app.modules.dependencies import Admin, Db
from app.modules.media.service import delete_message_media
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
from app.security import hash_web_password

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
        .order_by(Assignment.created_at.desc()),
    ).all()
    active_conversation_count = db.scalar(
        select(func.count(Conversation.id)).where(Conversation.status == "active"),
    ) or 0

    saved_positions: dict[str, dict[int, int]] = {}
    for item in db.scalars(select(GraphPosition)).all():
        saved_positions.setdefault(item.group_key, {})[item.user_id] = item.position

    def graph_sort(items: list[dict], group_key: str) -> list[dict]:
        positions = saved_positions.get(group_key, {})
        return sorted(items, key=lambda item: (positions.get(item["id"], len(items)), item["full_name"].casefold()))

    students_by_teacher: dict[int, list[dict]] = {}
    for assignment in assignments:
        students_by_teacher.setdefault(assignment.teacher_id, []).append(
            user_dict(assignment.student, include_additional_info=True),
        )

    teachers = []
    for user in users:
        if user.role != "teacher":
            continue
        students = graph_sort(
            students_by_teacher.get(user.id, []),
            f"students:{user.id}",
        )
        teachers.append({**user_dict(user), "students": students})
    teachers = graph_sort(teachers, "teachers")

    assigned_ids = {assignment.student_id for assignment in assignments}
    unassigned_students = graph_sort(
        [
            user_dict(user, include_additional_info=True)
            for user in users
            if user.role == "student" and user.id not in assigned_ids
        ],
        "unassigned",
    )

    return {
        "admin": {"label": "Администратор", "role": "admin"},
        "unassigned_students": unassigned_students,
        "counts": {
            "teachers": sum(1 for user in users if user.role == "teacher"),
            "students": sum(1 for user in users if user.role == "student"),
            "assignments": len(assignments),
            "conversations": active_conversation_count,
            "messages": db.query(Message).count(),
        },
        "teachers": teachers,
    }


@router.patch("/admin/graph/order")
def save_graph_order(payload: dict, _: Admin, db: Db):
    group = payload.get("group")
    user_ids = payload.get("user_ids")
    if not isinstance(group, str) or not isinstance(user_ids, list) or any(
        type(user_id) is not int or user_id < 1 for user_id in user_ids
    ):
        raise HTTPException(status_code=400, detail="Некорректный порядок участников")
    if len(user_ids) != len(set(user_ids)):
        raise HTTPException(status_code=400, detail="Список участников содержит повторяющиеся ID")

    if group == "teachers":
        expected_ids = set(db.scalars(select(User.id).where(User.role == "teacher")).all())
    elif group == "unassigned":
        assigned_ids = select(Assignment.student_id).where(Assignment.active.is_(True))
        expected_ids = set(db.scalars(
            select(User.id).where(User.role == "student", ~User.id.in_(assigned_ids)),
        ).all())
    elif group.startswith("students:") and group.removeprefix("students:").isdigit():
        teacher_id = int(group.removeprefix("students:"))
        teacher = db.get(User, teacher_id)
        if not teacher or teacher.role != "teacher":
            raise HTTPException(status_code=404, detail="Учитель не найден")
        expected_ids = set(db.scalars(
            select(Assignment.student_id).where(
                Assignment.teacher_id == teacher_id,
                Assignment.active.is_(True),
            ),
        ).all())
    else:
        raise HTTPException(status_code=400, detail="Неизвестная группа участников")

    if set(user_ids) != expected_ids:
        raise HTTPException(status_code=409, detail="Состав облачка изменился. Обновите страницу и повторите перемещение.")

    db.query(GraphPosition).filter(GraphPosition.group_key == group).delete(synchronize_session=False)
    db.add_all(
        GraphPosition(group_key=group, user_id=user_id, position=position)
        for position, user_id in enumerate(user_ids)
    )
    db.commit()
    return {"ok": True, "group": group, "user_ids": user_ids}


@router.get("/admin/users")
def list_users(_: Admin, db: Db):
    users = db.scalars(select(User).where(User.role.in_(["teacher", "student"])).order_by(User.role, User.full_name)).all()
    return [user_dict(user, include_additional_info=True) for user in users]


@router.post("/admin/users", status_code=201)
def create_user(payload: dict, _: Admin, db: Db):
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
        telegram_id=payload.get("telegram_id"),
        web_password_hash=hash_web_password(issued_access_code) if issued_access_code else None,
    )
    db.add(user)
    try:
        db.flush()
        if user.telegram_id is not None:
            sync_messenger_account(
                db, user.id, MessengerPlatform.TELEGRAM,
                str(user.telegram_id), external_chat_id=str(user.telegram_id),
            )
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
    except (IntegrityError, MessengerAccountConflict):
        db.rollback()
        raise HTTPException(status_code=409, detail="Этот Telegram ID уже используется")
    result = user_dict(user)
    if issued_access_code:
        result["issued_access_code"] = issued_access_code
    return result


@router.patch("/admin/users/{user_id}")
def update_user(user_id: int, payload: dict, _: Admin, db: Db):
    payload = user_update_payload(payload)
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    changes = payload
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
            ConnectionCode.expires_at > datetime.now(UTC),
        ),
    ).all()
    has_active_access_code = bool(user.web_password_hash and active_access_codes)
    if has_web_panel and (role_changed or not has_active_access_code):
        issued_access_code = generate_panel_access_code()
        user.web_password_hash = hash_web_password(issued_access_code)
    elif not has_web_panel:
        user.web_password_hash = None

    if role_changed:
        db.query(TeacherPanel).filter(TeacherPanel.teacher_id == user.id).delete(synchronize_session=False)
        assignments = db.scalars(select(Assignment).where(Assignment.active.is_(True), (Assignment.teacher_id == user.id) | (Assignment.student_id == user.id))).all()
        now = datetime.now(UTC)
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
            value = ((value or "").strip() or None) if target_role == "student" else None
        if field == "full_name" and value is not None:
            value = value.strip()
            if len(value) < 2:
                raise HTTPException(status_code=400, detail="Имя должно содержать минимум два символа")
        setattr(user, field, value)
    if issued_access_code:
        now = datetime.now(UTC)
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
        ).update({ConnectionCode.used_at: datetime.now(UTC)}, synchronize_session=False)
    try:
        if "telegram_id" in changes:
            sync_messenger_account(
                db,
                user.id,
                MessengerPlatform.TELEGRAM,
                str(user.telegram_id) if user.telegram_id is not None else None,
                external_chat_id=str(user.telegram_id) if user.telegram_id is not None else None,
            )
        db.commit()
        db.refresh(user)
    except MessengerAccountConflict:
        db.rollback()
        raise HTTPException(status_code=409, detail="Этот Telegram ID уже используется")
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
    now = datetime.now(UTC)
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

    # Remove only the Telegram binding. The persistent access code remains valid
    # for both participant roles and can be used to reconnect the same account.
    user.telegram_id = None
    sync_messenger_account(
        db, user.id, MessengerPlatform.TELEGRAM, None,
    )

    # A disconnected teacher must select a conversation again after reconnecting.
    if user.role == "teacher":
        db.query(TeacherSession).filter(
            TeacherSession.teacher_id == user.id,
        ).delete(synchronize_session=False)

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
        db.query(TeacherSession).filter(
            TeacherSession.conversation_id.in_(conversation_ids),
        ).delete(synchronize_session=False)
        db.query(Message).filter(
            Message.conversation_id.in_(conversation_ids),
        ).delete(synchronize_session=False)
        db.query(Conversation).filter(
            Conversation.id.in_(conversation_ids),
        ).delete(synchronize_session=False)

    # Удаляем все служебные ссылки до пользователя: SQLite теперь проверяет внешние ключи.
    db.query(PanelSession).filter(PanelSession.user_id == user.id).delete(synchronize_session=False)
    db.query(StudentTelegramGroup).filter(
        StudentTelegramGroup.student_id == user.id,
    ).delete(synchronize_session=False)
    db.query(TeacherSession).filter(
        TeacherSession.teacher_id == user.id,
    ).delete(synchronize_session=False)
    db.query(TeacherPanel).filter(TeacherPanel.teacher_id == user.id).delete(synchronize_session=False)
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
def generate_connection_code(user_id: int, _: Admin, db: Db):
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

@router.post("/admin/assignments", status_code=201)
def assign_student_route(payload: dict, _: Admin, db: Db):
    return assign_student(assignment_payload(payload), db)


@router.delete("/admin/assignments/{student_id}")
def unassign_student_route(student_id: int, _: Admin, db: Db):
    return unassign_student(student_id, db)



from app.admin_data import router as admin_data_router

router.include_router(admin_data_router)
