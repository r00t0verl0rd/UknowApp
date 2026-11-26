import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from aiogram.exceptions import TelegramForbiddenError
from aiogram.methods import GetChatMember

from connectors.telegram.adapter import TelegramAdapter
from connectors.telegram.teacher_panel import TeacherPanel, render
from connectors.common.spool import EventSpool


@pytest.mark.parametrize("mode,base", [("cloud","https://api.telegram.org"), ("local","http://local-api:8081")])
def test_api_modes(mode, base, monkeypatch):
    monkeypatch.setenv("TELEGRAM_API_MODE", mode)
    monkeypatch.setenv("TELEGRAM_API_URL", "http://local-api:8081")
    adapter = TelegramAdapter(None, "123:" + "a" * 32)
    try:
        assert adapter.max_attachment_bytes == (20 if mode == "cloud" else 888) * 1024 ** 2
        assert adapter.base == base
        assert adapter.bot.session.api.is_local == (mode == "local")
    finally:
        asyncio.run(adapter.close())


def test_local_streams_large_file(tmp_path, monkeypatch):
    monkeypatch.setenv("TELEGRAM_API_MODE", "local")
    monkeypatch.setenv("TELEGRAM_FILES_DIR", str(tmp_path))
    source = tmp_path / "file.bin"
    with source.open("wb") as f:
        f.truncate(21 * 1024 * 1024)
    async def run():
        adapter = TelegramAdapter(None, "123:" + "a" * 32)
        try:
            count = 0
            async for chunk in adapter.chunks(str(source)):
                assert len(chunk) <= 65536
                count += len(chunk)
            assert count == source.stat().st_size
        finally:
            await adapter.close()
    asyncio.run(run())


def test_private_and_topic_calls_and_delete():
    async def run():
        adapter = object.__new__(TelegramAdapter)
        adapter.bot = SimpleNamespace(send_message=AsyncMock(return_value=SimpleNamespace(message_id=12)),
                                     delete_message=AsyncMock())
        for chat, thread in [("200", None), ("-1001","7")]:
            assert await adapter.send({"chat_id":chat,"thread_id":thread,"kind":"text","text":"hello"}, None) == 12
            await adapter.delete({"chat_id":chat,"external_message_id":"12"})
        assert adapter.bot.send_message.await_args_list[0].kwargs == {"chat_id":200,"text":"hello"}
        assert adapter.bot.send_message.await_args_list[1].kwargs["message_thread_id"] == 7
        assert adapter.bot.delete_message.await_count == 2
    asyncio.run(run())


def test_teacher_panel_edits_background_without_extra_message(tmp_path):
    view = {"account":{"role":"teacher"}, "conversations":[{"id":1,"name":"Student","unread":1,
            "last_message":"hi","unread_previews":["hi"]}]}
    async def run():
        spool = EventSpool(tmp_path / "spool.db", "bot")
        bot = SimpleNamespace(send_message=AsyncMock(return_value=SimpleNamespace(message_id=123)),
                              edit_message_text=AsyncMock(), delete_message=AsyncMock())
        panel = TeacherPanel(bot)
        gateway = SimpleNamespace(rpc=AsyncMock(return_value=view))
        try:
            await panel.refresh("42", gateway, spool, view=view)
            assert spool.panel("42")["message_id"] == 123
            view["conversations"][0]["unread"] = 2
            await panel.refresh("42", gateway, spool, background=True)
            assert bot.send_message.await_count == 1
            assert bot.edit_message_text.await_count == 1
            assert bot.delete_message.await_count == 0
        finally:
            spool.close()
    asyncio.run(run())



def test_parallel_fanout_reuses_file_id():
    from collections import OrderedDict
    from aiogram.types import URLInputFile

    async def run():
        bot = SimpleNamespace(
            send_photo=AsyncMock(return_value=SimpleNamespace(message_id=123, photo=[SimpleNamespace(file_id="cached-photo")])),
            send_video=AsyncMock(), send_voice=AsyncMock(), send_audio=AsyncMock(),
            send_animation=AsyncMock(), send_document=AsyncMock())
        adapter = object.__new__(TelegramAdapter)
        adapter.bot = bot
        adapter.file_ids = OrderedDict()
        adapter.media_locks = {}
        gateway = SimpleNamespace(media_url=lambda job_id: "http://backend/media/" + job_id, headers={})
        media = {"file_name":"one.jpg", "key":"immutable"}
        a = {"id":"a","chat_id":"10","kind":"photo","text":"hi","media":media}
        b = {**a,"id":"b","chat_id":"20"}
        assert await asyncio.gather(adapter.send(a, gateway), adapter.send(b, gateway)) == [123,123]
        calls = bot.send_photo.await_args_list
        assert isinstance(calls[0].kwargs["photo"], URLInputFile)
        assert calls[1].kwargs["photo"] == "cached-photo"
        assert not adapter.media_locks

    asyncio.run(run())


@pytest.mark.parametrize("mode,mib", [("cloud", 20), ("local", 888)])
def test_oversize_outbound_rejected_before_provider_call(mode, mib, monkeypatch):
    from connectors.common.client import DeliveryRejected
    monkeypatch.setenv("TELEGRAM_API_MODE", mode)
    async def run():
        adapter = TelegramAdapter(None, "123:" + "a" * 32)
        try:
            job = {"chat_id": "10", "text": "", "kind": "document",
                   "media": {"file_size": mib * 1024 ** 2 + 1}}
            with pytest.raises(DeliveryRejected):
                await adapter.send(job, None)
        finally:
            await adapter.close()
    asyncio.run(run())


def test_local_oversize_rejected_before_read(tmp_path, monkeypatch):
    monkeypatch.setenv("TELEGRAM_API_MODE", "local")
    monkeypatch.setenv("TELEGRAM_FILES_DIR", str(tmp_path))
    source = tmp_path / "big.bin"
    with source.open("wb") as f:
        f.truncate(888 * 1024 ** 2 + 1)
    async def run():
        adapter = TelegramAdapter(None, "123:" + "a" * 32)
        try:
            with pytest.raises(ValueError, match="invalid local media"):
                async for _ in adapter.chunks(str(source)):
                    pytest.fail("oversized file read")
        finally:
            await adapter.close()
    asyncio.run(run())


@pytest.mark.parametrize("mode,mib", [("cloud", 20), ("local", 888)])
@pytest.mark.parametrize("declared_size", [True, False])
def test_inbound_oversize_marked_unavailable(mode, mib, declared_size, monkeypatch):
    monkeypatch.setenv("TELEGRAM_API_MODE", mode)
    limit = mib * 1024 ** 2
    async def run():
        adapter = TelegramAdapter(None, "123:" + "a" * 32)
        original_bot = adapter.bot
        adapter.bot = SimpleNamespace(
            get_file=AsyncMock(return_value=SimpleNamespace(file_size=limit + 1, file_path="file.bin")))
        gateway = SimpleNamespace(
            rpc=AsyncMock(return_value={"account": {"role": "student"}, "conversations": [{"id": 1}]}),
            upload=AsyncMock(), inbound=AsyncMock())
        try:
            document = {"file_id": "x"}
            if declared_size:
                document["file_size"] = limit + 1
            update = {"message": {"from": {"id": 10}, "chat": {"id": 10, "type": "private"},
                                  "message_id": 1, "document": document}}
            await adapter.handle("event", update, gateway, None)
            gateway.upload.assert_not_awaited()
            assert gateway.inbound.await_args.args[0]["media_unavailable"] is True
            assert adapter.bot.get_file.await_count == (0 if declared_size else 1)
        finally:
            await original_bot.session.close()
    asyncio.run(run())


@pytest.mark.parametrize("role", ["student", "teacher", None])
def test_forum_message_uses_actual_sender_and_topic(role):
    async def run():
        adapter = object.__new__(TelegramAdapter)
        adapter.bot = SimpleNamespace(send_message=AsyncMock(), get_chat_member=AsyncMock(), me=AsyncMock())
        gateway = SimpleNamespace(
            rpc=AsyncMock(return_value={"account": {"role": role} if role else None,
                                        "conversations": [{"id": 1}]}),
            inbound=AsyncMock(),
        )
        message = {"from": {"id": 10}, "chat": {"id": -1001, "type": "supergroup", "is_forum": True},
                   "message_thread_id": 47, "message_id": 48, "text": "Домашнее задание"}
        await adapter.handle("message", {"message": message}, gateway, None)
        gateway.rpc.assert_awaited_once_with("account.resolve", actor="10")
        adapter.bot.get_chat_member.assert_not_awaited()
        adapter.bot.me.assert_not_awaited()
        adapter.bot.send_message.assert_not_awaited()
        if role == "student":
            event = gateway.inbound.await_args.args[0]
            assert (event["actor"], event["chat_id"], event["thread_id"], event["channel"]) == (
                "10", "-1001", "47", "group")
            assert event["text"] == "Домашнее задание"
        else:
            gateway.inbound.assert_not_awaited()
    asyncio.run(run())


def test_forum_join_without_known_topic_and_old_command_are_silent():
    async def run():
        adapter = object.__new__(TelegramAdapter)
        adapter.bot = SimpleNamespace(send_message=AsyncMock())
        gateway = SimpleNamespace(rpc=AsyncMock(), inbound=AsyncMock())
        chat = {"id": -1001, "type": "supergroup", "is_forum": True}
        message = {"from": {"id": 50}, "chat": chat, "message_thread_id": 7, "message_id": 8}
        updates = [
            {"my_chat_member": {"chat": chat, "new_chat_member": {"status": "administrator"}}},
            {"chat_member": {"chat": chat, "new_chat_member": {"status": "member"}}},
            {"message": {**message, "new_chat_members": [{"id": 10}]}},
            {"message": {**message, "text": "/bind_group"}},
            {"message": {**message, "text": "anonymous", "sender_chat": chat}},
            {"message": {**message, "text": "no topic", "message_thread_id": None}},
        ]
        for index, update in enumerate(updates):
            await adapter.handle(str(index), update, gateway, None)
        gateway.rpc.assert_not_awaited()
        gateway.inbound.assert_not_awaited()
        adapter.bot.send_message.assert_not_awaited()
    asyncio.run(run())


@pytest.mark.parametrize("bot_status", ["administrator", "member"])
@pytest.mark.parametrize("thread,is_topic,inviter,added,expected", [
    (47, True, 50, 99, True),
    (None, False, 50, 99, False),
    (1, False, 50, 99, False),
    (47, True, 10, 99, False),
    (47, True, 50, 98, False),
])
def test_only_admin_invitation_of_this_bot_in_specific_topic_binds(thread, is_topic, inviter, added, expected, bot_status, tmp_path):
    async def run():
        adapter = object.__new__(TelegramAdapter)
        async def member(chat, actor):
            return SimpleNamespace(status={99: bot_status, 50: "administrator", 10: "member", 11: "left"}[actor])
        adapter.bot = SimpleNamespace(
            me=AsyncMock(return_value=SimpleNamespace(id=99, can_read_all_group_messages=True)),
            get_chat_member=AsyncMock(side_effect=member),
            get_chat_administrators=AsyncMock(return_value=[SimpleNamespace(user=SimpleNamespace(id=50))]),
            send_message=AsyncMock(),
        )
        gateway = SimpleNamespace(rpc=AsyncMock(side_effect=[
            {"actors": ["10", "11"], "next": None}, {"bound": True},
        ]), inbound=AsyncMock())
        spool = EventSpool(tmp_path / "forum.db", "bot")
        try:
            chat = {"id": -1001, "type": "supergroup", "is_forum": True}
            await adapter.handle("join", {"my_chat_member": {"chat": chat,
                "new_chat_member": {"status": bot_status}}}, gateway, spool)
            for name in ("Бот", "English"):
                await adapter.handle(name, {"message": {"from": {"id": 50}, "chat": chat,
                    "message_id": 7, "message_thread_id": 7, "forum_topic_created": {"name": name}}},
                    gateway, spool)
            gateway.rpc.assert_not_awaited()
            await adapter.handle("invite", {"message": {"from": {"id": inviter}, "chat": chat,
                "message_id": 8, "message_thread_id": thread, "is_topic_message": is_topic,
                "new_chat_members": [{"id": added, "is_bot": True}]}}, gateway, spool)
            if expected:
                gateway.rpc.assert_any_await("endpoint.bind", actor="10", chat_id="-1001",
                                             thread_id="47")
            else:
                gateway.rpc.assert_not_awaited()
            assert spool.forum_topic("-1001") is None
            adapter.bot.send_message.assert_not_awaited()
            gateway.inbound.assert_not_awaited()
        finally:
            spool.close()
    asyncio.run(run())


def test_pending_invited_topic_binds_when_student_joins(tmp_path):
    async def run():
        adapter = object.__new__(TelegramAdapter)
        adapter.bot = SimpleNamespace(me=AsyncMock(return_value=SimpleNamespace(id=99)),
            get_chat_member=AsyncMock(side_effect=[
                SimpleNamespace(status="administrator"), SimpleNamespace(status="member"),
            ]), send_message=AsyncMock())
        gateway = SimpleNamespace(rpc=AsyncMock(side_effect=[
            {"actors": ["10"], "next": None}, {"bound": True},
        ]), inbound=AsyncMock())
        spool = EventSpool(tmp_path / "forum.db", "bot")
        try:
            spool.remember_forum_topic("-1001", "7")
            await adapter.handle("member", {"chat_member": {"chat": {"id": -1001,
                "type": "supergroup", "is_forum": True}, "new_chat_member": {
                    "status": "member", "user": {"id": 10}}}}, gateway, spool)
            gateway.rpc.assert_any_await("endpoint.bind", actor="10", chat_id="-1001",
                                         thread_id="7")
            assert spool.forum_topic("-1001") is None
            adapter.bot.send_message.assert_not_awaited()
            gateway.inbound.assert_not_awaited()
        finally:
            spool.close()
    asyncio.run(run())


def test_regular_bot_unavailable_membership_does_not_block_student_message(tmp_path):
    async def run():
        adapter = object.__new__(TelegramAdapter)
        denied = TelegramForbiddenError(method=GetChatMember(chat_id=-1001, user_id=10),
                                        message="Forbidden")
        adapter.bot = SimpleNamespace(
            me=AsyncMock(return_value=SimpleNamespace(id=99, can_read_all_group_messages=True)),
            get_chat_member=AsyncMock(side_effect=[SimpleNamespace(status="member"), denied]),
            get_chat_administrators=AsyncMock(return_value=[SimpleNamespace(user=SimpleNamespace(id=50))]),
            send_message=AsyncMock(),
        )
        gateway = SimpleNamespace(rpc=AsyncMock(side_effect=[
            {"actors": ["10"], "next": None},
            {"account": {"role": "student"}, "conversations": [{"id": 1}]},
        ]), inbound=AsyncMock())
        spool = EventSpool(tmp_path / "forum.db", "bot")
        try:
            chat = {"id": -1001, "type": "supergroup", "is_forum": True}
            await adapter.handle("invite", {"message": {"from": {"id": 50}, "chat": chat,
                "message_id": 8, "message_thread_id": 47, "is_topic_message": True,
                "new_chat_members": [{"id": 99, "is_bot": True}]}}, gateway, spool)
            assert spool.forum_topic("-1001") == "47"
            await adapter.handle("student", {"message": {"from": {"id": 10}, "chat": chat,
                "message_id": 9, "message_thread_id": 47, "is_topic_message": True,
                "text": "Homework"}}, gateway, spool)
            assert gateway.rpc.await_count == 2
            assert gateway.inbound.await_args.args[0]["thread_id"] == "47"
            assert gateway.inbound.await_args.args[0]["actor"] == "10"
            adapter.bot.send_message.assert_not_awaited()
        finally:
            spool.close()
    asyncio.run(run())
