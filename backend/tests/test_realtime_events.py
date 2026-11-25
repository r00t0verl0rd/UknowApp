import json

from app.event_hub import current_event_id, replay_chat_updates, reset_replay
from app.models import Assignment, Conversation, User
from app.modules.conversations.service import publish_conversation_update


def test_ram_events_replay_only_for_conversation_members(api):
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
        first_id = current_event_id()
        publish_conversation_update(
            db, conversation, action="read", actor_role="student",
            message_ids=[1], read_at="2026-11-21T10:00:00+00:00",
        )
        second_id = current_event_id()

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
        latest = current_event_id()
        assert latest > second_id
        delivery = json.loads(replay_chat_updates(db, {"role": "admin"}, second_id)[0][1])
        assert delivery["action"] == "delivery" and "summary" not in delivery
        missed = replay_chat_updates(db, {"role": "admin"}, first_id)
        assert json.loads(missed[0][1]) == {"event_id": latest, "resync": True}


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


def test_bulk_read_stores_only_a_scoped_recovery_signal(api):
    from app.event_hub import publish_chat_update

    _, users, sessions = api
    audience = {"teacher_id": users["teacher-one"]}
    teacher = {"role": "teacher", "user_id": users["teacher-one"]}
    with sessions() as db:
        publish_chat_update(1, audience=audience, db=db)
        cursor = current_event_id()
        publish_chat_update(1, audience=audience, db=db, action="read", message_ids=list(range(1, 10001)))
        event = current_event_id()
        payload = replay_chat_updates(db, teacher, cursor)[0][1]
        assert len(payload.encode()) < 100
        assert json.loads(payload) == {"event_id": event, "resync": True}
        assert replay_chat_updates(db, {"role": "teacher", "user_id": users["teacher-two"]}, cursor) == []


def test_delivery_event_skips_summary_recount(api, monkeypatch):
    from app.modules.conversations import service
    from helpers import create_conversation

    _, users, sessions = api
    with sessions() as db:
        chat = create_conversation(db, users["teacher-one"], users["student-one"])
        def unexpected(*args):
            raise AssertionError("delivery event must not recompute conversation summary")
        monkeypatch.setattr(service, "conversation_event_summaries", unexpected)
        cursor = current_event_id()
        publish_conversation_update(db, chat, message_id=1, action="delivery")
        payload = json.loads(replay_chat_updates(db, {"role": "admin"}, cursor)[0][1])
        assert payload["action"] == "delivery"
        assert "summary" not in payload


def test_ram_replay_and_publish_do_not_touch_sql_and_restart_resyncs(api):
    from sqlalchemy import event, inspect
    from app.event_hub import publish_chat_update
    _, _, sessions = api
    with sessions() as db:
        assert not inspect(db.get_bind()).has_table("realtime_events")
        cursor = current_event_id()
        statements = []
        def count(*args):
            statements.append(args[2])
        event.listen(db.get_bind(), "before_cursor_execute", count)
        try:
            latest = publish_chat_update(1, audience={"teacher_id": 1}, db=db)
            assert latest > cursor
            assert replay_chat_updates(db, {"role": "teacher", "user_id": 1}, cursor)
            reset_replay()
            assert json.loads(replay_chat_updates(db, {"role": "admin"}, latest)[0][1])["resync"]
            assert json.loads(replay_chat_updates(db, {"role": "admin"}, current_event_id()+100)[0][1])["resync"]
            assert not statements
        finally:
            event.remove(db.get_bind(), "before_cursor_execute", count)
