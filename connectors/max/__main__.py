"""Receive MAX webhooks on the school server and acknowledge after a durable write."""
import asyncio
import fcntl
import hashlib
import hmac
import json
import logging
import os
import ssl
from pathlib import Path

import aiohttp
from aiohttp import web

from connectors.common.client import GatewayClient
from connectors.common.ingress import forward
from connectors.common.spool import EventSpool, MAX_EVENTS
from .adapter import MaxAdapter
from .webhook import WebhookMonitor

STATE = Path(os.getenv("CONNECTOR_STATE_DIR", "/app/state"))


def application(spool, secret, monitor=None):
    app = web.Application(client_max_size=1024 * 1024)

    async def receive(request):
        if not hmac.compare_digest(request.headers.get("X-Max-Bot-Api-Secret", "").encode(), secret.encode()):
            raise web.HTTPForbidden()
        try:
            update = await request.json()
        except (ValueError, TypeError):
            raise web.HTTPBadRequest() from None
        if not isinstance(update, dict):
            raise web.HTTPBadRequest()
        if update.get("update_type") in {"message_created", "message_callback", "bot_started"}:
            if spool.count() + spool.inbound_count() >= MAX_EVENTS:
                raise web.HTTPServiceUnavailable()
            key = json.dumps(update, sort_keys=True, separators=(",", ":")).encode()
            ident = hashlib.sha256(key).hexdigest()
            spool.append([(ident, update)], 0)
            if monitor is not None:
                monitor.event_received()
        return web.Response()

    app.router.add_post("/hooks/max", receive)
    return app


async def heartbeat(path):
    while True:
        path.touch()
        await asyncio.sleep(15)


async def main():
    STATE.mkdir(parents=True, exist_ok=True)
    secret = os.environ["MAX_WEBHOOK_SECRET"]
    context = ssl.create_default_context()
    ca = Path("/app/certs/max-ca.pem")
    if ca.is_file():
        context.load_verify_locations(cafile=ca)
    with (STATE / "worker.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=context),
                                         timeout=aiohttp.ClientTimeout(total=300)) as http:
            adapter = MaxAdapter(http, os.environ["MAX_BOT_TOKEN"])
            info = await adapter.api("GET", "/me")
            spool = EventSpool(STATE / "inbox.sqlite3", str(info["user_id"]))
            gateway = GatewayClient("max", http, spool)
            monitor = WebhookMonitor(adapter, os.environ["MAX_WEBHOOK_URL"], secret)
            runner = web.AppRunner(application(spool, secret, monitor), access_log=None)
            tasks = []
            try:
                await gateway.connect()
                await runner.setup()
                await web.TCPSite(runner, "0.0.0.0", 8080).start()
                tasks = [asyncio.create_task(coro) for coro in (
                    forward(adapter, gateway, spool), gateway.deliveries(adapter),
                    gateway.publish_inbound(), gateway.report_health(extra=monitor.diagnostics),
                    heartbeat(STATE / "healthy"), monitor.run())]
                await asyncio.gather(*tasks)
            finally:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                await runner.cleanup()
                await gateway.close()
                spool.close()
                (STATE / "healthy").unlink(missing_ok=True)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
