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


def test_live_sse_stream_delivers_bot_and_web_messages_to_all_roles(api, monkeypatch):
    """Exercise the real gateway, database, event hub and SSE response iterator."""
    import asyncio
    from types import SimpleNamespace
    from app.bots_gateway.operations import receive_message
    from app.bots_gateway.gateway import media_path
    from app.modules.communication.accounts import sync_messenger_account
    from app.modules.panel import session as panel_session
    from helpers import create_conversation

    make_client, users, sessions = api
    monkeypatch.setattr(panel_session, "SessionLocal", sessions)
    with sessions() as db:
        chat = create_conversation(db, users["teacher-one"], users["student-one"])
        chat_id = chat.id
        sync_messenger_account(db, users["student-one"], "telegram", "200", "200")
        db.commit()

    credentials = [
        ("admin", None, "test-admin", "a-long-test-password-123"),
        ("teacher", users["teacher-one"], "teacher-one", "teacher-password-1"),
        ("student", users["student-one"], "student-one", "student-password-1"),
    ]
    clients = {}
    for role, _, username, password in credentials:
        client = make_client()
        assert client.post("/api/auth/login", json={"username": username, "password": password}).status_code == 200
        clients[role] = client

    def incoming():
        with sessions() as db:
            receive_message(db, "telegram", {
                "id": "sse-test-inbound", "external_message_id": "42", "actor": "200",
                "chat_id": "200", "channel": "private", "kind": "text",
                "text": "Telegram SSE",
            }, (), media_path)

    async def connected():
        return False

    async def read_message(iterator, expected):
        frame = await asyncio.wait_for(anext(iterator), 3)
        assert frame.startswith("id: ") and frame.endswith("\n\n")
        assert "event: update\n" in frame
        payload = json.loads(next(line[6:] for line in frame.splitlines() if line.startswith("data: ")))
        assert payload["action"] == "upsert"
        assert payload["message_id"] == payload["message"]["id"]
        assert payload["message"]["text"] == expected
        return payload

    async def run():
        streams = {}
        try:
            for role, user_id, _, _ in credentials:
                request = SimpleNamespace(headers={}, cookies=dict(clients[role].cookies),
                                          is_disconnected=connected)
                response = await panel_session.panel_events(request, {"role": role, "user_id": user_id})
                assert response.media_type == "text/event-stream"
                iterator = response.body_iterator
                streams[role] = iterator
                assert (await anext(iterator)).startswith("retry:")
                assert "event: checkpoint" in await anext(iterator)
            await asyncio.to_thread(incoming)
            for role, iterator in streams.items():
                payload = await read_message(iterator, "Telegram SSE")
                assert payload["message"]["can_delete"] == (role == "student")
                assert payload["summary"]["unread_count"] == (0 if role == "student" else 1)
                if role != "admin":
                    assert "source_chat_id" not in payload["message"]["metadata"]
                    assert "messenger_deliveries" not in payload["message"]["metadata"]
            first_message_id = payload["message_id"]
            assert payload["previous_message_id"] is None
            sent = await asyncio.to_thread(clients["teacher"].post,
                f"/api/panel/conversations/{chat_id}/messages", json={"text": "Web SSE"})
            assert sent.status_code == 201
            for role, iterator in streams.items():
                payload = await read_message(iterator, "Web SSE")
                assert payload["message"]["id"] == sent.json()["id"]
                assert payload["previous_message_id"] == first_message_id
                assert payload["message"]["can_delete"] == (role == "teacher")
        finally:
            for iterator in streams.values():
                await iterator.aclose()

    asyncio.run(run())


def test_sse_personal_message_is_hydrated_only_for_participants(api):
    from app.models import PersonalConversation, PersonalMessage
    from app.modules.panel.session import visible_payload
    _, users, sessions = api
    with sessions() as db:
        chat = PersonalConversation(participant_id=users["student-one"])
        db.add(chat)
        db.flush()
        message = PersonalMessage(conversation_id=chat.id, sender_id=None,
                                  sender_role="admin", text="Private SSE")
        db.add(message)
        db.commit()
        hint = json.dumps({"conversation_id": chat.id, "conversation_type": "personal",
                           "action": "upsert", "message_id": message.id})
        admin = json.loads(visible_payload(db, {"role": "admin", "user_id": None}, hint))
        student = json.loads(visible_payload(db, {"role": "student", "user_id": users["student-one"]}, hint))
        outsider = json.loads(visible_payload(db, {"role": "teacher", "user_id": users["teacher-one"]}, hint))
        assert admin["message"]["can_delete"] is True
        assert student["message"]["can_delete"] is False
        assert student["message"]["text"] == "Private SSE"
        assert outsider == {"resync": True}
