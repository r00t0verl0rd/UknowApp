"""Retry and ordering checks for the persistent secondary gateway spool."""
import asyncio
import json

import aiohttp
from aiohttp import web

from app.modules.telegram import gateway


def test_secondary_retries_failed_primary_in_order(monkeypatch, tmp_path):
    async def run():
        monkeypatch.setattr(gateway, "SPOOL_PATH", tmp_path / "spool.sqlite3")
        monkeypatch.setattr(gateway, "GATEWAY_TOKEN", "k" * 64)
        gateway.init_spool()
        with gateway.connection() as db:
            for update_id in (111, 112):
                db.execute(
                    "INSERT INTO telegram_updates(update_id, payload) VALUES (?, ?)",
                    (update_id, json.dumps({"update_id": update_id})),
                )
        seen = []
        stop = asyncio.Event()

        async def inbound(request):
            assert request.headers["X-Uknow-Gateway-Key"] == gateway.GATEWAY_TOKEN
            payload = await request.json()
            seen.append(payload["update_id"])
            if seen == [111]:
                return web.Response(status=503)
            if payload["update_id"] == 112:
                stop.set()
            return web.Response(status=202)

        primary = web.Application()
        primary.router.add_post("/api/internal/telegram/updates", inbound)
        runner = web.AppRunner(primary)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        monkeypatch.setattr(gateway, "PRIMARY_URL", f"http://127.0.0.1:{port}")
        try:
            async with aiohttp.ClientSession() as session:
                await asyncio.wait_for(gateway.spool_worker(session, stop), timeout=12)
            assert seen == [111, 111, 112]
            with gateway.connection() as db:
                assert db.execute("SELECT COUNT(*) FROM telegram_updates").fetchone()[0] == 0
        finally:
            await runner.cleanup()

    asyncio.run(run())
