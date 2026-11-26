import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest

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


@pytest.mark.parametrize("name,bound", [("🤖 Бот", True), ("Бот", True), ("Домашнее задание", False)])
def test_dedicated_topic_is_bound_before_first_inbound_message(name, bound):
    async def run():
        adapter = object.__new__(TelegramAdapter)

        async def member(chat, actor):
            return SimpleNamespace(status={99: "administrator", 10: "member", 11: "left"}[actor])

        adapter.bot = SimpleNamespace(
            me=AsyncMock(return_value=SimpleNamespace(id=99)),
            get_chat_member=AsyncMock(side_effect=member),
            send_message=AsyncMock(),
        )
        gateway = SimpleNamespace(
            rpc=AsyncMock(side_effect=[
                {"actors": ["10", "11"], "next": None},
                {"bound": True},
            ]),
            inbound=AsyncMock(),
        )
        # The creator is an unrelated group administrator, not the student.
        update = {"message": {"from": {"id": 50},
                              "chat": {"id": -1001, "type": "supergroup", "is_forum": True},
                              "message_id": 7, "message_thread_id": 7,
                              "forum_topic_created": {"name": name}}}
        await adapter.handle("topic-created", update, gateway, None)
        gateway.inbound.assert_not_awaited()
        if bound:
            gateway.rpc.assert_any_await("endpoint.bind", actor="10", chat_id="-1001",
                                         thread_id="7", initial_only=True)
            adapter.bot.send_message.assert_awaited_once()
        else:
            gateway.rpc.assert_not_awaited()
            adapter.bot.send_message.assert_not_awaited()
    asyncio.run(run())


def test_group_join_prompts_for_binding_without_guessing_topic():
    async def run():
        adapter = object.__new__(TelegramAdapter)
        adapter.bot = SimpleNamespace(send_message=AsyncMock())
        gateway = SimpleNamespace(rpc=AsyncMock(), inbound=AsyncMock())
        update = {"my_chat_member": {"from": {"id": 50},
            "chat": {"id": -1001, "type": "supergroup", "is_forum": True},
            "old_chat_member": {"status": "left"},
            "new_chat_member": {"status": "administrator"}}}
        assert adapter.inbound_route(update) == ("group:-1001", False)
        await adapter.handle("joined", update, gateway, None)
        assert "/bind_group" in adapter.bot.send_message.await_args.args[1]
        gateway.rpc.assert_not_awaited()
        gateway.inbound.assert_not_awaited()
    asyncio.run(run())


@pytest.mark.parametrize("students,status", [([], "no_student"), ([10, 11], "ambiguous"), ([10], "bound")])
def test_group_binding_requires_exactly_one_linked_student(students, status):
    async def run():
        adapter = object.__new__(TelegramAdapter)

        async def member(chat, actor):
            return SimpleNamespace(status="administrator" if actor == 99 else "member" if actor in students else "left")

        adapter.bot = SimpleNamespace(me=AsyncMock(return_value=SimpleNamespace(id=99)),
                                      get_chat_member=AsyncMock(side_effect=member))
        gateway = SimpleNamespace(rpc=AsyncMock(side_effect=[
            {"actors": ["10"], "next": 1},
            {"actors": ["11"], "next": None},
            {"bound": True},
        ]))
        assert await adapter.bind_forum_student("-1001", "7", gateway) == status
        assert gateway.rpc.await_count == (3 if status == "bound" else 2)
    asyncio.run(run())


def test_existing_topic_can_be_bound_by_group_admin_not_student():
    async def run():
        adapter = object.__new__(TelegramAdapter)

        async def member(chat, actor):
            return SimpleNamespace(status="administrator" if actor in (50, 99) else "member")

        adapter.bot = SimpleNamespace(me=AsyncMock(return_value=SimpleNamespace(id=99)),
                                      get_chat_member=AsyncMock(side_effect=member), send_message=AsyncMock())
        gateway = SimpleNamespace(rpc=AsyncMock(side_effect=[
            {"actors": ["10"], "next": None}, {"bound": True},
        ]), inbound=AsyncMock())
        message = {"from": {"id": 50}, "chat": {"id": -1001, "type": "supergroup", "is_forum": True},
                   "message_thread_id": 7, "text": "/bind_group", "message_id": 8}
        await adapter.handle("admin-command", {"message": message}, gateway, None)
        gateway.rpc.assert_any_await("endpoint.bind", actor="10", chat_id="-1001", thread_id="7", initial_only=True)
        gateway.inbound.assert_not_awaited()
    asyncio.run(run())


def test_student_added_after_topic_creation_is_detected(tmp_path):
    async def run():
        spool = EventSpool(tmp_path / "forum.db", "bot")
        try:
            adapter = object.__new__(TelegramAdapter)
            adapter.bot = SimpleNamespace(me=AsyncMock(return_value=SimpleNamespace(id=99)),
                get_chat_member=AsyncMock(side_effect=[
                    SimpleNamespace(status="administrator"), SimpleNamespace(status="member"),
                ]), send_message=AsyncMock())
            gateway = SimpleNamespace(rpc=AsyncMock(side_effect=[
                {"actors": ["10"], "next": None}, {"bound": True},
            ]), inbound=AsyncMock())
            spool.remember_forum_topic("-1001", "7")
            update = {"chat_member": {"from": {"id": 50}, "chat": {"id": -1001, "type": "supergroup", "is_forum": True},
                "old_chat_member": {"status": "left"}, "new_chat_member": {"status": "member", "user": {"id": 10}}}}
            await adapter.handle("member-added", update, gateway, spool)
            gateway.rpc.assert_any_await("endpoint.bind", actor="10", chat_id="-1001", thread_id="7", initial_only=True)
            gateway.inbound.assert_not_awaited()
        finally:
            spool.close()
    asyncio.run(run())
