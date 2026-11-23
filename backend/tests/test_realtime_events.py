import json

from app.event_hub import replay_chat_updates
from app.models import Assignment, Conversation, RealtimeEvent, User
from app.modules.conversations.service import publish_conversation_update


def test_durable_events_replay_only_for_conversation_members(api):
    _, users, sessions = api
    with sessions() as db:
        teacher = db.get(User, users["teacher-one"])
        student = db.get(User, users["student-one"])
        other_teacher = db.get(User, users["teacher-two"])
        assignment = Assignment(
            teacher_id=teacher.id,
            student_id=student.id,
            active=True,
        )
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

        publish_conversation_update(db, conversation, action="upsert")
        first_id = db.query(RealtimeEvent.id).order_by(RealtimeEvent.id.desc()).first()[0]
        publish_conversation_update(
            db, conversation, action="read", actor_role="student",
            message_ids=[1], read_at="2026-11-21T10:00:00+00:00",
        )
        second_id = db.query(RealtimeEvent.id).order_by(RealtimeEvent.id.desc()).first()[0]

        teacher_events = replay_chat_updates(
            db, {"role": "teacher", "user_id": teacher.id}, first_id,
        )
        student_events = replay_chat_updates(
            db, {"role": "student", "user_id": student.id}, first_id,
        )
        unrelated_events = replay_chat_updates(
            db, {"role": "teacher", "user_id": other_teacher.id}, first_id,
        )

        assert [event_id for event_id, _ in teacher_events] == [second_id]
        assert [event_id for event_id, _ in student_events] == [second_id]
        assert unrelated_events == []
        teacher_payload = json.loads(teacher_events[0][1])
        assert teacher_payload["action"] == "read"
        assert teacher_payload["message_ids"] == [1]
        assert teacher_payload["summary"]["unread_count"] == 0
        publish_conversation_update(db, conversation, action="delivery")
        latest = db.query(RealtimeEvent).one()
        assert latest.id > second_id
        missed = replay_chat_updates(db, {"role": "admin"}, first_id)
        assert json.loads(missed[0][1]) == {"event_id": latest.id, "resync": True}


def test_revoked_assignment_redacts_queued_event(api):
    from app.modules.panel.session import visible_payload
    from app.modules.assignments.service import assign_student, unassign_student

    _, users, sessions = api
    teacher_id = users["teacher-one"]
    student_id = users["student-one"]
    teacher = {"role": "teacher", "user_id": teacher_id}
    with sessions() as db:
        chat = assign_student({"teacher_id": teacher_id, "student_id": student_id}, db)
        payload = json.dumps({"conversation_id": chat["id"], "conversation_type": "conversation", "summary": {"text": "private"}})
        assert visible_payload(db, teacher, payload) == payload
        unassign_student(student_id, db)
        assert json.loads(visible_payload(db, teacher, payload)) == {"resync": True}
