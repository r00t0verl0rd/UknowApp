"""End-to-end aiogram remote transport against a local fake Bot API server.

This exercises real HTTP multipart uploads/downloads without a Telegram token.
"""
import asyncio
import io
import json
from datetime import UTC, datetime

from aiohttp import web

from app.modules.communication.contracts import (
    MessageKind, MessengerPlatform, OutboundMedia, OutboundMessage,
)
from app.modules.telegram.adapter import TelegramAdapter
from app.modules.telegram.remote_transport import create_remote_bot


def test_bot_api_transport_streamed_files_and_commands(tmp_path):
    async def run():
        seen = []
        key = "b" * 64

        async def method(request):
            assert request.headers.get("X-Uknow-Gateway-Key") == key
            body = await request.post()
            method_name = request.match_info["method"]
            seen.append((method_name, dict(body)))
            if method_name == "getFile":
                result = {
                    "file_id": "file-1",
                    "file_unique_id": "unique-1",
                    "file_size": 5,
                    "file_path": "photos/hello.txt",
                }
            elif method_name == "copyMessage":
                result = {"message_id": 95}
            elif method_name in {"deleteMessage", "answerCallbackQuery"}:
                result = True
            else:
                result = {
                    "message_id": 96,
                    "date": 1760000000,
                    "chat": {"id": 35, "type": "private"},
                }
            return web.json_response({"ok": True, "result": result})

        async def file(request):
            assert request.headers.get("X-Uknow-Gateway-Key") == key
            return web.Response(body=b"hello")

        fake = web.Application()
        fake.router.add_post("/bot{token}/{method}", method)
        fake.router.add_get("/file/bot{token}/{path:.*}", file)
        runner = web.AppRunner(fake)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        bot = create_remote_bot(f"http://127.0.0.1:{port}", key)
        try:
            adapter = TelegramAdapter(bot, media_dir=tmp_path)
            assert await adapter.send_text("35", "Hi") == "96"
            assert await adapter.copy_message("35", "51", "35") == "95"
            await adapter.delete_message("35", "95")
            assert await bot.answer_callback_query("callback-1") is True

            (tmp_path / "small.jpg").write_bytes(b"fake-image")
            delivery = await adapter.send(
                OutboundMessage(
                    platform=MessengerPlatform.TELEGRAM,
                    external_chat_id="35",
                    content_type=MessageKind.PHOTO,
                    media=OutboundMedia(
                        storage_key="small.jpg",
                        file_name="small.jpg",
                        mime_type="image/jpeg",
                    ),
                )
            )
            assert delivery.external_message_id == "96"
            contents = await bot.download("file-1")
            assert contents.read() == b"hello"

            methods = [name for name, _ in seen]
            assert methods == [
                "sendMessage", "copyMessage", "deleteMessage",
                "answerCallbackQuery", "sendPhoto", "getFile",
            ]
            assert any(getattr(item, "filename", None) == "small.jpg" for item in seen[4][1].values())
        finally:
            await bot.session.close()
            await runner.cleanup()

    asyncio.run(run())
