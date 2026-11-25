"""Shared panel recipient selection and attachment storage."""
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Conversation, User


def panel_sender_and_recipients(db: Session, principal: dict, conversation: Conversation):
    """Определить отправителя и адресатов для сообщения."""
    student = conversation.student
    teacher = conversation.teacher
    if principal["role"] == "teacher":
        sender = teacher
        recipients = [(student, "student")]
    elif principal["role"] == "student":
        sender = student
        recipients = [(teacher, "teacher")]
    else:
        sender = db.scalar(select(User).where(User.role == "admin").order_by(User.id).limit(1))
        if not sender:
            sender = User(full_name="Администратор", role="admin")
            db.add(sender)
            db.flush()
        recipients = [(student, "student"), (teacher, "teacher")]
    if not sender:
        raise HTTPException(status_code=401, detail="Учётная запись недоступна")
    return sender, recipients, student, teacher
