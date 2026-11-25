"""Telegram transport worker. No Core imports, database credentials or shared app_data."""
import asyncio
import logging
import os
import time
from pathlib import Path
from urllib.parse import quote

import aiohttp

from connectors.common.client import GatewayClient
from connectors.common.spool import EventSpool, MAX_EVENTS

logger = logging.getLogger(__name__)
# Only methods used by the current Core adapter and teacher interface.
METHODS = frozenset({
    "getMe", "getChatMember", "getFile", "sendMessage", "copyMessage",
    "sendPhoto", "sendAnimation", "sendVideo", "sendVoice", "sendAudio",
    "sendDocument", "deleteMessage", "editMessageText", "editMessageReplyMarkup",
    "answerCallbackQuery",
})
MAX_BYTES = 1024 ** 3
STATE = Path(os.getenv("CONNECTOR_STATE_DIR", "/app/state"))


class Telegram:
    def __init__(self, session, token):
        self.session = session
        self.token = token
        mode = os.getenv("TELEGRAM_API_MODE", "cloud")
        if mode not in {"cloud", "local"}:
            raise ValueError("invalid Telegram API mode")
        self.local = mode == "local"
        self.base = (os.getenv("TELEGRAM_API_URL", "http://telegram-bot-api:8081")
                     if self.local else "https://api.telegram.org").rstrip("/")
        self.files = Path(os.getenv("TELEGRAM_FILES_DIR", "/var/lib/telegram-bot-api")).resolve()
        self.gateway = None
        self.last_poll = 0.0

    async def api(self, method, *, data=None, json_data=None, timeout=60):
        async with self.session.post(
            f"{self.base}/bot{self.token}/{method}", data=data, json=json_data,
            timeout=aiohttp.ClientTimeout(total=timeout), allow_redirects=False,
        ) as response:
            return response.status, await response.json(content_type=None)

    async def file_chunks(self, ticket):
        async with self.session.get(
            self.gateway.media_url(ticket), headers=self.gateway.headers,
            timeout=aiohttp.ClientTimeout(total=300), allow_redirects=False,
        ) as response:
            response.raise_for_status()
            count = 0
            async for chunk in response.content.iter_chunked(65536):
                count += len(chunk)
                if count > MAX_BYTES:
                    raise ValueError("file too large")
                yield chunk

    async def provider_chunks(self, path):
        if not isinstance(path, str) or not path or ".." in Path(path).parts:
            raise ValueError("invalid provider path")
        if self.local:
            source = Path(path)
            if not source.is_absolute():
                source = self.files / source
            source = source.resolve()
            if not source.is_relative_to(self.files) or not source.is_file():
                raise ValueError("provider file outside cache")
            if source.stat().st_size > MAX_BYTES:
                raise ValueError("file too large")
            with source.open("rb") as stream:
                while chunk := await asyncio.to_thread(stream.read, 65536):
                    yield chunk
        else:
            async with self.session.get(
                f"{self.base}/file/bot{self.token}/{quote(path, safe='/')}",
                timeout=aiohttp.ClientTimeout(total=300), allow_redirects=False,
            ) as response:
                response.raise_for_status()
                count = 0
                async for chunk in response.content.iter_chunked(65536):
                    count += len(chunk)
                    if count > MAX_BYTES:
                        raise ValueError("file too large")
                    yield chunk

    async def execute(self, operation, payload):
        if operation == "telegram.download":
            async with self.session.put(
                self.gateway.media_url(payload["ticket"]), headers=self.gateway.headers,
                data=self.provider_chunks(payload["path"]),
                timeout=aiohttp.ClientTimeout(total=300), allow_redirects=False,
            ) as response:
                response.raise_for_status()
                return {"ok": True}
        if operation != "telegram.api" or payload.get("method") not in METHODS:
            raise ValueError("unsupported operation")
        fields = payload.get("fields", {})
        files = payload.get("files", {})
        form = aiohttp.FormData(quote_fields=False)
        for key, value in fields.items():
            if not isinstance(value, str):
                raise ValueError("invalid Telegram form value")
            form.add_field(key, value)
        for key, item in files.items():
            form.add_field(key, self.file_chunks(item["ticket"]), filename=item["filename"],
                           content_type="application/octet-stream")
        status, body = await self.api(payload["method"], data=form, timeout=300 if files else 60)
        return {"status": status, "body": body}

    async def poll(self, spool, bot_id):
        delay = 1
        while True:
            if spool.count() >= MAX_EVENTS:
                # Do not acknowledge further provider events when local storage is full.
                await asyncio.sleep(2)
                continue
            try:
                params = {"timeout": 30, "allowed_updates": ["message", "callback_query"],
                          "limit": min(100, MAX_EVENTS - spool.count())}
                cursor = spool.cursor()
                if cursor is not None:
                    params["offset"] = cursor
                status, response = await self.api("getUpdates", json_data=params, timeout=45)
                if status == 409:
                    raise PollingConflict("another Telegram poller is active")
                if not response.get("ok"):
                    await asyncio.sleep(min(int(response.get("parameters", {}).get("retry_after", delay)), 60))
                    delay = min(delay * 2, 60)
                    continue
                updates = response["result"]
                if updates:
                    spool.append([(f"{bot_id}:{u['update_id']}", u) for u in updates],
                                 max(u["update_id"] for u in updates) + 1)
                self.last_poll = time.monotonic()
                delay = 1
            except (asyncio.CancelledError, PollingConflict):
                raise
            except Exception as exc:
                logger.warning("Telegram polling unavailable: %s", type(exc).__name__)
                await asyncio.sleep(delay)
                delay = min(delay * 2, 60)


class PollingConflict(RuntimeError):
    pass


async def main():
    token = os.environ["TELEGRAM_BOT_TOKEN"].strip()
    if not token:
        raise ValueError("Telegram token required")
    STATE.mkdir(parents=True, exist_ok=True)
    health = STATE / "healthy"
    health.unlink(missing_ok=True)
    async with aiohttp.ClientSession() as session:
        telegram = Telegram(session, token)
        # A short outage at startup must not require rebuilding/restarting Core.
        while True:
            try:
                _, info = await telegram.api("getMe")
                if info.get("ok"):
                    bot_id = info["result"]["id"]
                    break
            except Exception as exc:
                logger.warning("Telegram startup unavailable: %s", type(exc).__name__)
            await asyncio.sleep(5)
        spool = EventSpool(STATE / "inbox.sqlite3", str(bot_id))
        connected = False

        def status(value):
            nonlocal connected
            connected = value
            if not value:
                health.unlink(missing_ok=True)

        telegram.gateway = GatewayClient(session, os.environ["BOTS_GATEWAY_URL"], "telegram",
                                         os.environ["BOTS_GATEWAY_TELEGRAM_SECRET"], spool,
                                         telegram.execute, status)

        async def health_loop():
            while True:
                if connected and time.monotonic() - telegram.last_poll < 75:
                    health.touch()
                else:
                    health.unlink(missing_ok=True)
                await asyncio.sleep(5)

        logger.warning("TELEGRAM_CONNECTED id=%s", bot_id)
        async def start_polling():
            # Do not compete with embedded polling if Core was not switched to connector mode.
            while True:
                await telegram.gateway.ready.wait()
                try:
                    _, webhook = await telegram.api("deleteWebhook", json_data={"drop_pending_updates": False})
                    if webhook.get("ok"):
                        break
                except Exception as exc:
                    logger.warning("Telegram webhook setup unavailable: %s", type(exc).__name__)
                await asyncio.sleep(5)
            logger.warning("TELEGRAM_POLLING_STARTED")
            await telegram.poll(spool, bot_id)

        tasks = [asyncio.create_task(start_polling()),
                 asyncio.create_task(telegram.gateway.run()),
                 asyncio.create_task(health_loop())]
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        except PollingConflict:
            # Do not keep competing for getUpdates with an existing instance.
            logger.critical("TELEGRAM_POLLING_CONFLICT: stop the other poller and restart this container")
            health.unlink(missing_ok=True)
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await asyncio.Event().wait()
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            spool.close()
            health.unlink(missing_ok=True)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
