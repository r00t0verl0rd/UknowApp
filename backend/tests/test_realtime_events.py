import asyncio
import json

from app.event_hub import publish_chat_update, subscribe_chat_updates, unsubscribe_chat_updates
from app.models import (
    Assignment,
    Conversation,
    Message,
    PersonalConversation,
    PersonalMessage,
    User,
)
from app.modules.conversations.service import conversation_event_summaries
from app.modules.personal_chat.service import personal_event_summaries


def test_sse_events_are_scoped_and_include_role_specific_snapshots():
    async def exercise():
        teacher_queue = subscribe_chat_updates({"role": "teacher", "user_id": 7})
        student_queue = subscribe_chat_updates({"role": "student", "user_id": 9})
        other_queue = subscribe_chat_updates({"role": "teacher", "user_id": 11})
        admin_queue = subscribe_chat_updates({"role": "admin", "user_id": None})
        try:
            publish_chat_update(
                42,
                message_id=108,
                action="read",
                actor_role="student",
                message_ids=[101, 102],
                read_at="2026-11-21T10:00:00+00:00",
                audience={"teacher_id": 7, "student_id": 9},
                summary_by_role={
                    "teacher": {"id": 42, "unread_count": 0},
                    "student": {"id": 42, "unread_count": 3},
                    "admin": {"id": 42, "unread_count": 5},
                },
            )
            await asyncio.sleep(0.01)

            teacher_event = json.loads(teacher_queue.get_nowait())
            student_event = json.loads(student_queue.get_nowait())
            admin_event = json.loads(admin_queue.get_nowait())

            assert teacher_event["action"] == "read"
            assert teacher_event["message_ids"] == [101, 102]
            assert teacher_event["read_at"] == "2026-11-21T10:00:00+00:00"
            assert teacher_event["summary"]["unread_count"] == 0
            assert student_event["summary"]["unread_count"] == 3
            assert admin_event["summary"]["unread_count"] == 5
            assert "audience" not in teacher_event
            assert "summary_by_role" not in teacher_event
            assert other_queue.empty()
        finally:
            unsubscribe_chat_updates(teacher_queue)
            unsubscribe_chat_updates(student_queue)
            unsubscribe_chat_updates(other_queue)
            unsubscribe_chat_updates(admin_queue)

    asyncio.run(exercise())


def test_personal_sse_events_reach_only_admin_and_linked_participant():
    async def exercise():
        participant_queue = subscribe_chat_updates({"role": "teacher", "user_id": 7})
        admin_queue = subscribe_chat_updates({"role": "admin", "user_id": None})
        unrelated_queue = subscribe_chat_updates({"role": "student", "user_id": 9})
        try:
            publish_chat_update(
                5,
                conversation_type="personal",
                action="upsert",
                audience={"participant_id": 7},
                summary_by_role={
                    "admin": {"id": 5, "unread_count": 1},
                    "teacher": {"id": 5, "unread_count": 0},
                },
            )
            await asyncio.sleep(0.01)
            assert json.loads(participant_queue.get_nowait())["summary"]["unread_count"] == 0
            assert json.loads(admin_queue.get_nowait())["summary"]["unread_count"] == 1
            assert unrelated_queue.empty()
        finally:
            unsubscribe_chat_updates(participant_queue)
            unsubscribe_chat_updates(admin_queue)
            unsubscribe_chat_updates(unrelated_queue)

    asyncio.run(exercise())


def test_conversation_event_summaries_keep_role_counters_authoritative(api):
    _, users, sessions = api
    with sessions() as db:
        teacher = db.get(User, users["teacher-one"])
        student = db.get(User, users["student-one"])
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
        db.flush()
        db.add_all([
            Message(
                conversation_id=conversation.id,
                sender_id=student.id,
                sender_role="student",
                text="Вопрос",
                metadata_json=json.dumps({"teacher_read_at": None}),
                delivery_status="delivered",
            ),
            Message(
                conversation_id=conversation.id,
                sender_id=teacher.id,
                sender_role="teacher",
                text="Ответ",
                metadata_json=json.dumps({"student_read_at": None}),
                delivery_status="delivered",
            ),
        ])
        db.commit()

        summaries = conversation_event_summaries(db, conversation)
        assert summaries["teacher"]["message_count"] == 2
        assert summaries["teacher"]["unread_count"] == 1
        assert summaries["student"]["unread_count"] == 1
        assert summaries["admin"]["unread_count"] == 2


def test_personal_event_summaries_track_both_directions(api):
    _, users, sessions = api
    with sessions() as db:
        participant = db.get(User, users["teacher-one"])
        item = PersonalConversation(participant_id=participant.id)
        db.add(item)
        db.flush()
        db.add_all([
            PersonalMessage(
                conversation_id=item.id,
                sender_id=participant.id,
                sender_role="teacher",
                text="Сообщение участника",
            ),
            PersonalMessage(
                conversation_id=item.id,
                sender_id=None,
                sender_role="admin",
                text="Ответ администратора",
            ),
        ])
        db.commit()

        summaries = personal_event_summaries(db, item)
        assert summaries["admin"]["unread_count"] == 1
        assert summaries["teacher"]["unread_count"] == 1
