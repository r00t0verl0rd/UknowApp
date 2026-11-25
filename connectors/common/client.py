"""Transport shared by Telegram, MAX and future connectors.

Each connector initiates exactly one WebSocket to Core. Media travels over HTTP
using opaque, single-use tickets. Nothing here imports the Core or its ORM.
"""
import asyncio
import logging
from collections.abc import Awaitable, Callable

import aiohttp

logger = logging.getLogger(__name__)
PROTOCOL = 1
MAX_FRAME = 1024 * 1024
MAX_COMMANDS = 32


class GatewayClient:
    def __init__(self, session, base_url, platform, secret, spool, execute, on_connected=None):
        if len(secret) < 32:
            raise ValueError("connector secret must contain at least 32 characters")
        self.session = session
        self.base_url = base_url.rstrip("/")
        self.platform = platform
        self.headers = {"Authorization": "Bearer " + secret}
        self.spool = spool
        self.execute: Callable[[str, dict], Awaitable[dict]] = execute
        self.on_connected = on_connected or (lambda _: None)
        self.ready = asyncio.Event()

    def media_url(self, token):
        return f"{self.base_url}/internal/bots/media/{self.platform}/{token}"

    async def connected(self, ws):
        hello = await ws.receive_json(timeout=10)
        if hello != {"type": "hello", "version": PROTOCOL}:
            raise RuntimeError("incompatible gateway protocol")
        self.ready.set()
        self.on_connected(True)
        send_lock = asyncio.Lock()
        pending = {}
        commands = set()

        async def send(frame):
            async with send_lock:
                await ws.send_json(frame)

        async def execute(frame):
            try:
                result = await self.execute(frame["operation"], frame["payload"])
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Connector command failed: %s", type(exc).__name__)
                result = {"error": "connector operation failed"}
            await send({"type": "result", "id": frame["id"], "payload": result})

        async def forward():
            while True:
                event = self.spool.first()
                if event is None:
                    await asyncio.sleep(0.25)
                    continue
                event_id, payload = event
                ack = asyncio.get_running_loop().create_future()
                pending[event_id] = ack
                try:
                    await send({"type": "event", "id": event_id, "payload": payload})
                    ok = await asyncio.wait_for(ack, 900)
                    if ok:
                        self.spool.ack(event_id)
                    else:
                        await asyncio.sleep(5)
                finally:
                    pending.pop(event_id, None)

        async def receive():
            async for message in ws:
                if message.type != aiohttp.WSMsgType.TEXT:
                    break
                frame = message.json()
                if not isinstance(frame, dict):
                    raise RuntimeError("invalid frame")
                if frame.get("type") == "ack":
                    ack = pending.get(frame.get("id"))
                    if ack is not None and not ack.done():
                        ack.set_result(frame.get("ok") is True)
                elif frame.get("type") == "command":
                    if len(commands) >= MAX_COMMANDS:
                        await send({"type": "result", "id": frame["id"],
                                    "payload": {"error": "connector busy"}})
                        continue
                    task = asyncio.create_task(execute(frame))
                    commands.add(task)

                    def finished(done):
                        commands.discard(done)
                        if not done.cancelled() and done.exception() is not None:
                            logger.warning("Connector response could not be sent")
                    task.add_done_callback(finished)
                elif frame.get("type") != "pong":
                    raise RuntimeError("unknown gateway frame")

        tasks = [asyncio.create_task(receive()), asyncio.create_task(forward())]
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        finally:
            self.ready.clear()
            self.on_connected(False)
            active = tasks + list(commands)
            for task in active:
                task.cancel()
            await asyncio.gather(*active, return_exceptions=True)

    async def run(self):
        delay = 1
        while True:
            try:
                async with self.session.ws_connect(
                    f"{self.base_url}/internal/bots/ws/{self.platform}",
                    headers=self.headers, heartbeat=20, max_msg_size=MAX_FRAME,
                ) as ws:
                    delay = 1
                    await self.connected(ws)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Gateway connection unavailable: %s", type(exc).__name__)
            finally:
                self.on_connected(False)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 30)
