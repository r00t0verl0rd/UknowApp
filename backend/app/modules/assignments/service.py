"""Назначение учеников преподавателям."""

from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.event_hub import publish_chat_update
from app.models import Assignment, Conversation, TeacherSession, User
from app.modules.conversations.service import conversation_dict


def assign_student(payload, db: Session) -> dict:
    teacher = db.get(User, payload["teacher_id"])
    student = db.get(User, payload["student_id"])
    if not teacher or teacher.role != "teacher":
        raise HTTPException(status_code=400, detail="Выберите учителя")
    if not student or student.role != "student":
        raise HTTPException(status_code=400, detail="Выберите ученика")

    previous = db.scalars(
        select(Assignment).where(
            Assignment.student_id == student.id,
            Assignment.active.is_(True),
        ),
    ).all()

    # Повторное назначение не создаёт пустой диалог.
    current = next(
        (
            item.conversation
            for item in previous
            if item.teacher_id == teacher.id
            and item.conversation
            and item.conversation.status == "active"
        ),
        None,
    )
    if current:
        return conversation_dict(db, current)

    closed_conversation_ids = []
    for assignment in previous:
        conversation = assignment.conversation
        if conversation:
            conversation.status = "closed"
            conversation.assignment_id = None
            closed_conversation_ids.append(conversation.id)
            db.query(TeacherSession).filter(
                TeacherSession.conversation_id == conversation.id,
            ).delete(synchronize_session=False)
        db.delete(assignment)

    # Сохраняем изменения до поиска прежней переписки.
    db.flush()
    conversation = db.scalar(
        select(Conversation)
        .where(
            Conversation.teacher_id == teacher.id,
            Conversation.student_id == student.id,
            Conversation.status == "closed",
            Conversation.assignment_id.is_(None),
        )
        .order_by(Conversation.created_at.desc(), Conversation.id.desc())
        .limit(1),
    )

    assignment = Assignment(teacher_id=teacher.id, student_id=student.id, active=True)
    db.add(assignment)
    db.flush()

    if conversation:
        conversation.assignment_id = assignment.id
        conversation.status = "active"
    else:
        conversation = Conversation(
            assignment_id=assignment.id,
            teacher_id=teacher.id,
            student_id=student.id,
            status="active",
        )
        db.add(conversation)

    db.commit()
    db.refresh(conversation)

    for closed_id in closed_conversation_ids:
        if closed_id != conversation.id:
            publish_chat_update(closed_id)
    publish_chat_update(conversation.id)
    return conversation_dict(db, conversation)


def unassign_student(student_id: int, db: Session) -> dict:
    student = db.get(User, student_id)
    if not student or student.role != "student":
        raise HTTPException(status_code=404, detail="Ученик не найден")

    assignments = db.scalars(
        select(Assignment).where(
            Assignment.student_id == student.id,
            Assignment.active.is_(True),
        ),
    ).all()
    if not assignments:
        raise HTTPException(status_code=404, detail="Ученик не закреплён за учителем")

    now = datetime.now(UTC)
    conversation_ids = []
    for assignment in assignments:
        assignment.active = False
        assignment.closed_at = now
        if assignment.conversation:
            conversation = assignment.conversation
            conversation.status = "closed"
            conversation.assignment_id = None
            conversation_ids.append(conversation.id)
            db.query(TeacherSession).filter(
                TeacherSession.conversation_id == conversation.id,
            ).delete(synchronize_session=False)

    db.commit()
    for conversation_id in conversation_ids:
        publish_chat_update(conversation_id)
    return {"ok": True, "student_id": student.id}
