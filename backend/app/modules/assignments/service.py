"""Assignment lifecycle and teacher/student linking."""

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...event_hub import publish_chat_update
from ...models import Assignment, Conversation, User
from ..conversations.service import conversation_dict


def assign_student(payload, db: Session) -> dict:
    teacher = db.get(User, payload.teacher_id)
    student = db.get(User, payload.student_id)
    if not teacher or teacher.role != "teacher":
        raise HTTPException(status_code=400, detail="Выберите учителя")
    if not student or student.role != "student":
        raise HTTPException(status_code=400, detail="Выберите ученика")

    previous = db.scalars(
        select(Assignment).where(Assignment.student_id == student.id, Assignment.active.is_(True))
    ).all()
    for assignment in previous:
        if assignment.conversation:
            assignment.conversation.status = "closed"
            assignment.conversation.assignment_id = None
        db.delete(assignment)

    assignment = Assignment(teacher_id=teacher.id, student_id=student.id, active=True)
    db.add(assignment)
    db.flush()
    conversation = Conversation(
        assignment_id=assignment.id,
        teacher_id=teacher.id,
        student_id=student.id,
        status="active",
    )
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    publish_chat_update(conversation.id)
    return conversation_dict(db, conversation)



