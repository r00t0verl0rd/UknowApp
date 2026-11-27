import unittest
from unittest.mock import AsyncMock, Mock

from connectors.max.adapter import MaxAdapter


class MaxMessaging(unittest.IsolatedAsyncioTestCase):
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
        gateway.rpc.assert_awaited_once_with("account.resolve", actor="13", group=True, chat_id="-42")
        gateway.inbound.assert_not_awaited()
