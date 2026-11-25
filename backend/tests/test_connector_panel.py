"""Core supplies bounded, authorized, read-aware panel data; provider UI is outside Core."""
from app.bots_gateway.operations import rpc, receive_message
from app.bots_gateway.gateway import media_path
from app.models import Message
from app.modules.communication.accounts import sync_messenger_account
from helpers import create_conversation


def test_panel_preview_and_bounded_history(api):
    _, users, sessions = api
    with sessions() as db:
        chat = create_conversation(db, users["teacher-one"], users["student-one"])
        sync_messenger_account(db, chat.teacher_id, "alpha", "teacher")
        sync_messenger_account(db, chat.student_id, "alpha", "student")
        db.commit()
        for i in range(15):
            receive_message(db, "alpha", {"id":f"event-{i}", "actor":"student", "chat_id":"student",
                "channel":"private", "kind":"text", "text":f"message {i}"}, (), media_path)
        menu = rpc(db, "alpha", "conversation.list", {"actor":"teacher"})
        assert menu["conversations"][0]["unread"] == 15
        assert menu["conversations"][0]["unread_previews"] == ["message 12","message 13","message 14"]
        view = rpc(db, "alpha", "panel.sync", {"actor":"teacher","conversation_id":chat.id})
        assert view["chat"]["total"] == 15
        assert len(view["chat"]["messages"]) == 12
        assert view["conversations"][0]["unread"] == 15
        rpc(db, "alpha", "conversation.open", {"actor":"teacher","conversation_id":chat.id})
        assert rpc(db, "alpha", "conversation.list", {"actor":"teacher"})["conversations"][0]["unread"] == 3
        assert db.query(Message).count() == 15
