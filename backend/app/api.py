import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import aliased
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .database import SessionLocal
from .media_storage import MEDIA_DIR, delete_message_media
from .models import Assignment, ConnectionCode, Conversation, Message, TeacherPanel, TeacherSession, User
from .schemas import AssignmentCreate, LoginRequest, PanelMessageCreate, UserCreate, UserUpdate
from .security import authenticate_panel_user, hash_web_password, require_admin, require_panel_user, verify_admin

router = APIRouter(prefix="/api")


def get_db():
    with SessionLocal() as db:
        yield db


Admin = Annotated[str, Depends(require_admin)]
PanelUser = Annotated[dict, Depends(require_panel_user)]
Db = Annotated[Session, Depends(get_db)]


def user_dict(user: User) -> dict:
    return {
        "id": user.id,
        "full_name": user.full_name,
        "role": user.role,
        "telegram_id": user.telegram_id,
        "active": user.active,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "has_web_password": bool(user.web_password_hash),
    }


def conversation_dict(db: Session, conversation: Conversation) -> dict:
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
        "teacher": user_dict(assignment.teacher),
        "student": user_dict(assignment.student),
        "last_message": last_message.text if last_message else "Переписка пока пуста",
        "last_message_at": last_message.created_at.isoformat() if last_message else None,
        "message_count": count,
    }


@router.post("/auth/login")
def login(payload: LoginRequest):
    identity = authenticate_panel_user(payload.username, payload.password)\n    if not identity:\n        raise HTTPException(status_code=401, detail="Неверный логин или пароль")\n    return {"ok": True, "username": payload.username, **identity}


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
    user = User(full_name=payload.full_name.strip(), role=payload.role, telegram_id=payload.telegram_id)\n    if payload.web_password:\n        if payload.role != "teacher":\n            raise HTTPException(status_code=400, detail="Пароль веб-панели можно задать только учителю")\n        user.web_password_hash = hash_web_password(payload.web_password)
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
    changes = payload.model_dump(exclude_unset=True)\n    new_web_password = changes.pop("web_password", None)\n    if new_web_password:\n        if changes.get("role", user.role) != "teacher":\n            raise HTTPException(status_code=400, detail="Пароль веб-панели можно задать только учителю")\n        user.web_password_hash = hash_web_password(new_web_password)\n    role_changed = "role" in changes and changes["role"] != user.role
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
        media_type=media.get("mime_type") or "application/octet-stream",
        filename=media.get("file_name") or path.name,
        content_disposition_type="inline",
    )


def _panel_conversation_dict(db: Session, conversation: Conversation) -> dict:
    return conversation_dict(db, conversation)


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


def _panel_message_dict(item: Message) -> dict:
    return {
        "id": item.id,
        "sender": item.sender.full_name if item.sender else "Администратор",
        "sender_role": item.sender_role,
        "content_type": item.content_type,
        "text": item.text,
        "metadata": json.loads(item.metadata_json or "{}"),
        "delivery_status": item.delivery_status,
        "created_at": item.created_at.isoformat(),
    }


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
    return [_panel_conversation_dict(db, item) for item in conversations]


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
    return [_panel_message_dict(item) for item in rows]


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
        media_type=media.get("mime_type") or "application/octet-stream",
        filename=media.get("file_name") or path.name,
        content_disposition_type="inline",
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
    if not body:
        raise HTTPException(status_code=400, detail="Введите текст сообщения")

    if principal["role"] == "teacher":
        sender = db.get(User, principal["user_id"])
        recipients = [conversation.assignment.student]
    else:
        sender = db.scalar(select(User).where(User.role == "admin").order_by(User.id).limit(1))
        if not sender:
            sender = User(full_name="Администратор", role="admin", active=True)
            db.add(sender)
            db.flush()
        recipients = [conversation.assignment.student, conversation.assignment.teacher]

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
        for recipient in recipients:
            if not recipient.telegram_id or not recipient.active:
                delivery_errors.append(recipient.full_name + ": Telegram не подключён")
                continue
            try:
                prefix = ""
                if principal["role"] == "teacher":
                    prefix = "Сообщение от учителя " + sender.full_name + ":\n"
                else:
                    prefix = "Сообщение от администратора школы:\n"
                sent = await bot.send_message(chat_id=recipient.telegram_id, text=prefix + body)
                delivered.append({"user_id": recipient.id, "telegram_message_id": sent.message_id})
            except Exception as exc:
                delivery_errors.append(recipient.full_name + ": " + str(exc)[:180])
    else:
        delivery_errors.append("Telegram-бот не подключён к веб-приложению")

    metadata = json.loads(row.metadata_json or "{}")
    metadata["telegram_deliveries"] = delivered
    if delivery_errors:
        metadata["telegram_delivery_errors"] = delivery_errors
    row.metadata_json = json.dumps(metadata, ensure_ascii=False)
    row.delivery_status = "delivered" if delivered and not delivery_errors else ("partial" if delivered else "failed")
    db.commit()

    if principal["role"] == "admin" and bot and conversation.assignment.teacher.telegram_id:
        try:
            from .telegram_teacher import update_teacher_panel
            await update_teacher_panel(bot, db, conversation.assignment.teacher)
        except Exception:
            # Message is already persisted; a panel refresh failure must not undo it.
            pass

    return _panel_message_dict(row)
