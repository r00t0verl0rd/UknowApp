import tempfile
import unittest
from unittest.mock import AsyncMock, Mock

from connectors.common.spool import EventSpool
from connectors.max.adapter import MaxAdapter


class MaxMessaging(unittest.IsolatedAsyncioTestCase):
    async def test_background_updates_edit_unchanged_navigation(self):
        adapter = MaxAdapter(None, "test")
        adapter.api = AsyncMock(return_value={})
        adapter.message = AsyncMock(return_value="panel-new")
        gateway = Mock(rpc=AsyncMock(return_value={
            "account": {"role": "teacher"},
            "conversations": [{"id": 4, "name": "Ученица", "unread": 1,
                               "last_message": "Новое сообщение"}],
            "chat": None,
        }))
        with tempfile.TemporaryDirectory() as tmp:
            spool = EventSpool(f"{tmp}/max-spool.db", "max")
            try:
                await adapter.refresh_panel("42", gateway, spool)
                gateway.rpc.return_value["conversations"][0]["unread"] = 2
                await adapter.refresh_panel("42", gateway, spool, background=True)
                self.assertEqual(adapter.api.await_args.args[:2], ("PUT", "/messages"))
                adapter.message.assert_awaited_once()
                self.assertEqual(spool.panel("42")["mid"], "panel-new")
            finally:
                spool.close()

    async def test_old_teacher_buttons_are_not_forwarded_after_role_change(self):
        adapter = MaxAdapter(None, "test")
        adapter.api = AsyncMock(return_value={})
        adapter.message = AsyncMock(return_value="panel-new")
        gateway = Mock()
        student = {"account": {"role": "student"}, "conversations": [{"id": 4, "name": "Учитель"}]}
        gateway.rpc = AsyncMock(side_effect=lambda operation, **_: student)
        with tempfile.TemporaryDirectory() as tmp:
            spool = EventSpool(f"{tmp}/max-spool.db", "max")
            spool.save_panel("42", {"mid": "panel-old", "role": "teacher", "text": "Ваша группа",
                                    "buttons": ["Старый ученик"]})
            try:
                await adapter.handle("evt", {"update_type": "message_created", "message": {
                    "sender": {"user_id": 42}, "recipient": {"chat_type": "dialog"},
                    "body": {"text": "Старый ученик", "mid": "msg-1"},
                }}, gateway, spool)
                gateway.inbound.assert_not_called()
                self.assertEqual(adapter.api.await_args_list[0].args[:2], ("DELETE", "/messages"))
                adapter.message.assert_awaited_once_with("42", "Ваш преподаватель: Учитель")
                self.assertEqual(spool.panel("42")["mid"], "panel-new")
                self.assertEqual(spool.panel("42")["stale_buttons"], ["Старый ученик"])
            finally:
                spool.close()

    async def test_private_delivery_keeps_every_external_id(self):
        adapter = MaxAdapter(None, "test")
        adapter.message = AsyncMock(side_effect=["a", "b"])
        gateway = Mock()
        ids = await adapter.send({"id": "j", "recipient": "42", "text": "x" * 4001}, gateway)
        self.assertEqual(ids, ["a", "b"])
        self.assertEqual(adapter.message.await_args_list[0].args[:2], ("42", "x" * 4000))
        self.assertEqual(gateway.spool.record_delivery_part.call_count, 2)

    async def test_group_does_not_consume_private_link_code(self):
        adapter = MaxAdapter(None, "test")
        gateway = AsyncMock()
        gateway.rpc.return_value = {"route_allowed": False}
        await adapter.handle("evt", {"update_type": "message_created", "message": {
            "sender": {"user_id": 13}, "recipient": {"chat_type": "chat", "chat_id": -42},
            "body": {"text": "ABCD2345"}}}, gateway, Mock())
        gateway.rpc.assert_not_awaited()
        gateway.inbound.assert_not_awaited()

    async def test_teacher_panel_opens_after_binding_and_uses_student_buttons(self):
        adapter = MaxAdapter(None, "test")
        adapter.message = AsyncMock(return_value="panel-1")
        adapter.api = AsyncMock(return_value={})
        linked = False
        selected = None
        conversations = [{"id": 17, "name": "Алина", "unread": 1, "last_message": "Привет"}]
        teacher = {"role": "teacher"}

        async def rpc(operation, **payload):
            nonlocal linked, selected
            if operation == "conversation.list":
                return {"account": teacher if linked else None, "conversations": conversations if linked else []}
            if operation == "account.bind":
                linked = True
                return {"account": teacher, "conversations": conversations}
            if operation == "conversation.open":
                selected = payload["conversation_id"]
                return {"id": selected, "name": "Алина", "messages": [], "total": 0}
            if operation == "panel.sync":
                return {"account": teacher, "conversations": conversations,
                        "chat": {"id": selected, "name": "Алина", "messages": [], "total": 0}
                        if selected else None}
            raise AssertionError(operation)

        gateway = Mock(rpc=AsyncMock(side_effect=rpc))
        with tempfile.TemporaryDirectory() as tmp:
            spool = EventSpool(f"{tmp}/max-spool.db", "max")
            try:
                update = {"update_type": "message_created", "message": {
                    "sender": {"user_id": 42}, "recipient": {"chat_type": "dialog"},
                    "body": {"text": "ABCD2345", "mid": "msg-1"}}}
                await adapter.handle("event-1", update, gateway, spool)

                adapter.message.assert_awaited_once()
                text, keyboard = adapter.message.await_args.args[1:]
                self.assertIn("Алина", text)
                button = keyboard[0]["payload"]["buttons"][0][0]
                self.assertEqual(button, {"type": "callback", "text": "Алина", "payload": spool.panel("42")["revision"] + ":open:17"})

                update["message"]["body"]["text"] = "ABCD2345"
                await adapter.handle("event-2", update, gateway, spool)
                await adapter.handle("event-3", {"update_type": "message_callback", "callback": {
                    "callback_id": "callback-1", "payload": spool.panel("42")["revision"] + ":open:17",
                    "user": {"user_id": 42}, "message": {"body": {"mid": "panel-1"}},
                }}, gateway, spool)
                self.assertEqual(spool.selected_conversation("42"), 17)
                self.assertEqual(adapter.api.await_args_list[-1].args[:2], ("POST", "/answers"))

                await adapter.handle("event-4", {"update_type": "message_callback", "callback": {
                    "callback_id": "callback-2", "payload": spool.panel("42")["revision"] + ":back",
                    "user": {"user_id": 42}, "message": {"body": {"mid": "panel-1"}},
                }}, gateway, spool)
                self.assertIsNone(spool.selected_conversation("42"))
                self.assertEqual(adapter.api.await_args_list[-1].args[:2], ("POST", "/answers"))

                update["message"]["body"]["text"] = "Menu"
                await adapter.handle("event-5", update, gateway, spool)
                self.assertIsNone(spool.selected_conversation("42"))
                self.assertEqual(
                    sum(call.args[0] == "account.bind" for call in gateway.rpc.await_args_list), 2
                )
            finally:
                spool.close()

    async def test_stale_callback_never_changes_selection(self):
        adapter = MaxAdapter(None, "test")
        adapter.api = AsyncMock(return_value={})
        gateway = Mock(rpc=AsyncMock(), inbound=AsyncMock())
        with tempfile.TemporaryDirectory() as tmp:
            spool = EventSpool(f"{tmp}/spool.db", "max")
            try:
                spool.select_conversation("42", 17)
                spool.save_panel("42", {"mid": "new", "revision": "new-rev", "actions": ["open:18"]})
                for mid, payload in [("old", "new-rev:open:18"), ("new", "old-rev:open:18")]:
                    await adapter.handle_callback({"callback": {"callback_id": "cb", "user": {"user_id": 42},
                        "payload": payload, "message": {"body": {"mid": mid}}}}, gateway, spool)
                gateway.rpc.assert_not_awaited()
                self.assertEqual(spool.selected_conversation("42"), 17)
            finally:
                spool.close()
