"""Durable Telegram polling; Core never receives a provider token or SDK objects."""
import asyncio
import logging
import fcntl
import os
from pathlib import Path

import aiohttp
from aiogram.exceptions import TelegramConflictError

from connectors.common.client import GatewayClient
from connectors.common.ingress import forward
from connectors.common.spool import EventSpool, MAX_EVENTS
from .adapter import TelegramAdapter

logger = logging.getLogger(__name__)
STATE = Path(os.getenv("CONNECTOR_STATE_DIR", "/app/state"))


async def poll(adapter, spool, bot_id, health):
    while True:
        remaining = MAX_EVENTS - spool.count() - spool.inbound_count()
        if remaining <= 0:
            await asyncio.sleep(2)
            continue
        try:
            updates = await adapter.bot.get_updates(offset=spool.cursor(), timeout=30,
                limit=min(100, remaining), allowed_updates=["message", "callback_query"],
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


async def main():
    STATE.mkdir(parents=True, exist_ok=True)
    health = STATE / "healthy"
    health.unlink(missing_ok=True)
    # Do not allow concurrent workers on the same local durable spool.
    lock = (STATE / "worker.lock").open("a")
    try:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock.close()
        raise RuntimeError("connector state already in use") from None
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
                     asyncio.create_task(gateway.deliveries(adapter)),
                     asyncio.create_task(gateway.publish_inbound()),
                     asyncio.create_task(gateway.report_health())]
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
            lock.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
