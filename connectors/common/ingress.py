"""Bounded provider-neutral inbound dispatch, ordered by actor, no idle polling."""
import asyncio
import logging

from .client import RpcError

logger = logging.getLogger(__name__)


async def forward(adapter, gateway, spool):
    active = {}
    retries = {}

    async def process(ident, update):
        try:
            await adapter.handle(ident, update, gateway, spool)
        except RpcError as exc:
            if exc.code >= 500 or exc.code == 425:
                return False
            logger.warning("Core rejected provider event: %s", exc.code)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Provider event will retry: %s", type(exc).__name__)
            return False
        spool.ack(ident)
        return True

    try:
        while True:
            spool.changed.clear()
            now = asyncio.get_running_loop().time()
            for task, (ident, _, _) in list(active.items()):
                if task.done():
                    active.pop(task)
                    if task.result():
                        retries.pop(ident, None)
                    else:
                        retries[ident] = now + 5
            busy = {actor for _, actor, _ in active.values()}
            heavy_count = sum(heavy for _, _, heavy in active.values())
            for ident, update in spool.batch():
                if len(active) >= 4:
                    break
                actor, heavy = adapter.inbound_route(update)
                if actor in busy:
                    continue
                busy.add(actor)
                if retries.get(ident, 0) > now or heavy and heavy_count >= 2:
                    continue
                heavy_count += bool(heavy)
                task = asyncio.create_task(process(ident, update))
                active[task] = (ident, actor, heavy)
            delay = min((t - now for t in retries.values() if t > now), default=None)
            changed = asyncio.create_task(spool.changed.wait())
            try:
                await asyncio.wait([changed, *active], timeout=delay, return_when=asyncio.FIRST_COMPLETED)
            finally:
                changed.cancel()
                await asyncio.gather(changed, return_exceptions=True)
    finally:
        for task in active:
            task.cancel()
        await asyncio.gather(*active, return_exceptions=True)
