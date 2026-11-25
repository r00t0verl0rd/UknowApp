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
