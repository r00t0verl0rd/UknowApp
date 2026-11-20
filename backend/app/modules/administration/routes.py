"""HTTP API веб-панели: авторизация, участники, переписки и доставка сообщений."""

import hashlib
import logging
import math
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app.models import (
    Assignment,
    ConnectionCode,
    Conversation,
    GraphObject,
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


def _graph_object_dict(item: GraphObject) -> dict:
    return {
        "id": item.id, "key": item.object_key, "type": item.object_type,
        "title": item.title, "parent_id": item.parent_id, "x": item.x, "y": item.y,
    }


@router.get("/admin/graph/objects")
def graph_objects(_: Admin, db: Db):
    users = db.scalars(select(User).where(User.role.in_(["teacher", "student"]))).all()
    teachers = {user.id: user for user in users if user.role == "teacher"}
    students = {user.id: user for user in users if user.role == "student"}
    assignments = db.scalars(
        select(Assignment).where(Assignment.active.is_(True)).order_by(Assignment.created_at),
    ).all()
    assigned_to = {item.student_id: item.teacher_id for item in assignments if item.teacher_id in teachers}

    objects = {item.object_key: item for item in db.scalars(select(GraphObject)).all()}

    def ensure(key: str, kind: str, title: str, parent_id: int | None, x: float = 0, y: float = 0):
        item = objects.get(key)
        if item is None:
            item = GraphObject(object_key=key, object_type=kind, title=title, parent_id=parent_id, x=x, y=y)
            db.add(item)
            db.flush()
            objects[key] = item
        else:
            item.object_type, item.title, item.parent_id = kind, title, parent_id
        return item

    fon = ensure("fon", "fon", "Fon", None, 0, 0)
    admin = ensure("administrator", "administrator", "Администратор", fon.id, 32, 32)
    assigned_area = ensure("assigned_students", "area", "Назначенные ученики", admin.id, 0, 110)
    teachers_area = ensure("teachers", "area", "Учителя", admin.id, 500, 110)

    for teacher_id, teacher in teachers.items():
        ensure(f"teacher:{teacher_id}", "teacher", teacher.full_name, teachers_area.id)
    for student_id, student in students.items():
        parent = objects.get(f"teacher:{assigned_to[student_id]}") if student_id in assigned_to else None
        ensure(
            f"student:{student_id}", "student", student.full_name,
            parent.id if parent else assigned_area.id,
        )

    valid_keys = {"fon", "administrator", "assigned_students", "teachers"}
    valid_keys.update(f"teacher:{user_id}" for user_id in teachers)
    valid_keys.update(f"student:{user_id}" for user_id in students)
    valid_keys.update(key for key in objects if key.startswith("custom:"))
    for key, item in tuple(objects.items()):
        if key not in valid_keys:
            db.delete(item)

    db.commit()
    return [_graph_object_dict(item) for item in db.scalars(select(GraphObject).order_by(GraphObject.id)).all()]


@router.patch("/admin/graph/objects/{object_id}/position")
def update_graph_object_position(object_id: int, payload: dict, _: Admin, db: Db):
    x, y = payload.get("x"), payload.get("y")
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) or abs(value) > 100000 or not math.isfinite(value) for value in (x, y)):
        raise HTTPException(status_code=422, detail="Некорректные координаты объекта")
    item = db.get(GraphObject, object_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Объект графа не найден")
    item.x, item.y = x, y
    db.commit()
    return _graph_object_dict(item)


@router.post("/admin/graph/objects", status_code=201)
def create_graph_object(payload: dict, _: Admin, db: Db):
    title = str(payload.get("title") or "").strip()
    parent_id = payload.get("parent_id")
    object_type = str(payload.get("type") or "object").strip()
    if not title or len(title) > 160 or len(object_type) > 40:
        raise HTTPException(status_code=422, detail="Укажите название объекта")
    if parent_id is not None and db.get(GraphObject, parent_id) is None:
        raise HTTPException(status_code=404, detail="Родительский объект не найден")
    sibling_count = db.scalar(select(func.count(GraphObject.id)).where(GraphObject.parent_id == parent_id)) or 0
    parent = db.get(GraphObject, parent_id) if parent_id is not None else None
    base_y = 780 if parent and parent.object_type == "fon" else 560 if parent and parent.object_type == "administrator" else 90
    item = GraphObject(
        object_key=f"custom:{uuid.uuid4().hex}",
        object_type=object_type, title=title, parent_id=parent_id,
        x=36 + (sibling_count % 4) * 190, y=base_y + (sibling_count // 4) * 100,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return _graph_object_dict(item)


@router.delete("/admin/graph/objects/{object_id}")
def delete_graph_object(object_id: int, _: Admin, db: Db):
    item = db.get(GraphObject, object_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Объект графа не найден")
    if not item.object_key.startswith("custom:"):
        raise HTTPException(status_code=403, detail="Системные объекты удалять нельзя")

    pending = [item.id]
    descendants = []
    while pending:
        children = db.scalars(
            select(GraphObject).where(GraphObject.parent_id.in_(pending)),
        ).all()
        pending = [child.id for child in children]
        descendants.extend(children)

    if any(not child.object_key.startswith("custom:") for child in descendants):
        raise HTTPException(status_code=409, detail="Нельзя удалить объект с системными вложенными элементами")

    for child in reversed(descendants):
        db.delete(child)
    db.delete(item)
    db.commit()
    return {"deleted": True, "deleted_count": len(descendants) + 1}


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
