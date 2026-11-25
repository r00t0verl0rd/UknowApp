"""Durable Telegram polling; Core never receives a provider token or SDK objects."""
import asyncio
import logging
import os
from pathlib import Path

import aiohttp
from aiogram.exceptions import TelegramConflictError

from connectors.common.client import GatewayClient, RpcError
from connectors.common.spool import EventSpool, MAX_EVENTS
from .adapter import TelegramAdapter

logger = logging.getLogger(__name__)
STATE = Path(os.getenv("CONNECTOR_STATE_DIR", "/app/state"))


async def poll(adapter, spool, bot_id, health):
    while True:
        if spool.count() >= MAX_EVENTS:
            await asyncio.sleep(2)
            continue
        try:
            updates = await adapter.bot.get_updates(offset=spool.cursor(), timeout=30,
                limit=min(100, MAX_EVENTS - spool.count()), allowed_updates=["message", "callback_query"],
                request_timeout=45)
            if updates:
                spool.append([(f"{bot_id}:{u.update_id}", u.model_dump(mode="json", by_alias=True, exclude_none=True)) for u in updates],
                             max(u.update_id for u in updates) + 1)
            health.touch()
        except TelegramConflictError:
            health.unlink(missing_ok=True)
            logger.error("TELEGRAM_POLLING_CONFLICT: stop other poller")
            raise
        except Exception as exc:
            logger.warning("Provider polling unavailable: %s", type(exc).__name__)
            await asyncio.sleep(5)


async def forward(adapter, gateway, spool):
    while True:
        item = spool.first()
        if item is None:
            await asyncio.sleep(.25)
            continue
        event_id, update = item
        try:
            await adapter.handle(event_id, update, gateway, spool)
        except RpcError as exc:
            if exc.code >= 500:
                await asyncio.sleep(5)
                continue
            logger.warning("Core rejected provider event: %s", exc.code)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Provider event will retry: %s", type(exc).__name__)
            await asyncio.sleep(5)
            continue
        spool.ack(event_id)


async def main():
    STATE.mkdir(parents=True, exist_ok=True)
    health = STATE / "healthy"
    health.unlink(missing_ok=True)
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=300)) as http:
        adapter = TelegramAdapter(http, os.environ["TELEGRAM_BOT_TOKEN"])
        spool = gateway = None
        tasks = []
        try:
            info = await adapter.bot.get_me()
            spool = EventSpool(STATE / "inbox.sqlite3", str(info.id))
            gateway = GatewayClient("telegram", http, spool)
            await gateway.connect()
            await gateway.rpc("account.resolve", actor=str(info.id))
            await adapter.bot.delete_webhook(drop_pending_updates=False)
            logger.info("TELEGRAM_CONNECTED id=%s; TELEGRAM_POLLING_STARTED", info.id)
            tasks = [asyncio.create_task(poll(adapter, spool, info.id, health)),
                     asyncio.create_task(forward(adapter, gateway, spool)),
                     asyncio.create_task(gateway.deliveries(adapter))]
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        except TelegramConflictError:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await asyncio.Event().wait()
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            if gateway:
                await gateway.close()
            if spool:
                spool.close()
            await adapter.close()
            health.unlink(missing_ok=True)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
