import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .database import SessionLocal
from .models import Assignment, ConnectionCode, Conversation, Message, TeacherSession, User
from .schemas import AssignmentCreate, LoginRequest, UserCreate, UserUpdate
from .security import require_admin, verify_admin

router = APIRouter(prefix="/api")


def get_db():
    with SessionLocal() as db:
        yield db


Admin = Annotated[str, Depends(require_admin)]
Db = Annotated[Session, Depends(get_db)]


def user_dict(user: User) -> dict:
    return {
        "id": user.id,
        "full_name": user.full_name,
        "role": user.role,
        "telegram_id": user.telegram_id,
        "active": user.active,
        "created_at": user.created_at.isoformat() if user.created_at else None,
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
    if not verify_admin(payload.username, payload.password):
        raise HTTPException(status_code=401, detail="Неверный логин или пароль")
    return {"ok": True, "username": payload.username}


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
    users = db.scalars(select(User).order_by(User.role, User.full_name)).all()
    return [user_dict(user) for user in users]


@router.post("/admin/users", status_code=201)
def create_user(payload: UserCreate, _: Admin, db: Db):
    user = User(full_name=payload.full_name.strip(), role=payload.role, telegram_id=payload.telegram_id)
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
    role_changed = "role" in changes and changes["role"] != user.role
    if role_changed:
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
    conversations = db.scalars(
        select(Conversation).join(Assignment).order_by(Conversation.created_at.desc())
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
