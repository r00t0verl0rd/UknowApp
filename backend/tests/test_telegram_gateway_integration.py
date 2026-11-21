"""Integration test: aiogram -> secondary HTTP gateway -> fake Telegram.

All services run on local loopback. No real Telegram messages or secrets.
"""
import asyncio

import aiohttp
import uvicorn
from aiohttp import web

from app.modules.telegram import gateway
from app.modules.telegram.remote_transport import create_remote_bot


def test_secondary_gateway_forwards_authenticated_bot_api_and_file(monkeypatch):
    async def run():
        key = "s" * 64
        observed = []

        async def telegram_method(request):
            method = request.match_info["method"]
            body = await request.post()
            observed.append((method, dict(body)))
            if method == "getFile":
                result = {
                    "file_id": "abc", "file_unique_id": "xyz",
                    "file_path": "photos/sample.dat",
                }
            else:
                result = {"message_id": 123, "date": 1760000000, "chat": {"id": 1234, "type": "private"}}
            return web.json_response({"ok": True, "result": result})

        async def telegram_file(request):
            return web.Response(body=b"download-ok")

        fake = web.Application()
        fake.router.add_post("/bot{token}/{method}", telegram_method)
        fake.router.add_get("/file/bot{token}/{path:.*}", telegram_file)
        runner = web.AppRunner(fake)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        upstream_port = site._server.sockets[0].getsockname()[1]

        monkeypatch.setattr(gateway, "BOT_TOKEN", "123456:test-BotFather-token")
        monkeypatch.setattr(gateway, "GATEWAY_TOKEN", key)
        monkeypatch.setattr(gateway, "TELEGRAM_API_URL", f"http://127.0.0.1:{upstream_port}")

        async with aiohttp.ClientSession() as proxy_client:
            gateway.app.state.client = proxy_client
            server = uvicorn.Server(
                uvicorn.Config(
                    gateway.app,
                    host="127.0.0.1",
                    port=0,
                    lifespan="off",
                    log_level="error",
                    access_log=False,
                )
            )
            task = asyncio.create_task(server.serve())
            bot = None
            try:
                for _ in range(100):
                    if server.started:
                        break
                    await asyncio.sleep(0.05)
                assert server.started
                proxy_port = server.servers[0].sockets[0].getsockname()[1]
                origin = f"http://127.0.0.1:{proxy_port}"
                bot = create_remote_bot(origin, key)
                assert (await bot.send_message(1234, "hello remote")).message_id == 123
                assert (await bot.download("abc")).read() == b"download-ok"
                assert [method for method, _ in observed] == ["sendMessage", "getFile"]

                async with aiohttp.ClientSession() as unauthorized:
                    async with unauthorized.post(
                        origin + "/bot1000000:REMOTE_GATEWAY_TRANSPORT/sendMessage",
                        data={"chat_id": "1", "text": "bad"},
                    ) as forbidden:
                        assert forbidden.status == 401
            finally:
                if bot is not None:
                    await bot.session.close()
                server.should_exit = True
                await task
                await runner.cleanup()

    asyncio.run(run())
