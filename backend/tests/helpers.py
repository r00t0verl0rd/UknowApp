from app.models import Assignment, Conversation

def create_conversation(db, teacher_id, student_id):
    assignment = Assignment(
        teacher_id=teacher_id, student_id=student_id, active=True,
    )
    db.add(assignment)
    db.flush()
    conversation = Conversation(
        assignment_id=assignment.id,
        teacher_id=teacher_id,
        student_id=student_id,
        status="active",
    )
    db.add(conversation)
    db.commit()
    return conversation


