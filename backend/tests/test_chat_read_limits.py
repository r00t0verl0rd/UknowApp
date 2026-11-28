import asyncio

import httpx
from fastapi import APIRouter, FastAPI

from app.core import chat_read_limits as limits
from app.modules.panel import conversations, personal, sync


def test_chat_read_routes_are_explicit_and_exclude_uploads():
    for module in (conversations, personal, sync):
        for route in module.router.routes:
            assert isinstance(route, limits.ChatReadRoute)
            for method in route.methods:
                expected = ((method == "GET" and not route.path.endswith("/media"))
                            or (method == "POST" and route.path.endswith(("/sync", "/read"))))
                assert route.is_chat_read(method) == expected


def test_read_requests_are_bounded_and_writes_and_media_bypass(monkeypatch):
    monkeypatch.setattr(limits, "CHAT_READ_CONCURRENCY", 2)

    async def run():
        app = FastAPI()
        router = APIRouter(route_class=limits.ChatReadRoute)
        release = asyncio.Event()
        entered = asyncio.Event()
        active = maximum = count = 0

        @router.get("/history")
        async def history():
            nonlocal active, maximum, count
            active += 1
            count += 1
            maximum = max(maximum, active)
            if active == 2:
                entered.set()
            try:
                await release.wait()
                return {"ok": True}
            finally:
                active -= 1

        @router.post("/messages")
        async def send():
            return {"ok": True}

        @router.get("/messages/1/media")
        async def media():
            return {"ok": True}

        app.include_router(router)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            tasks = [asyncio.create_task(client.get("/history")) for _ in range(8)]
            try:
                await asyncio.wait_for(entered.wait(), 2)
                assert count == 2
                assert (await asyncio.wait_for(client.post("/messages"), 2)).status_code == 200
                assert (await asyncio.wait_for(client.get("/messages/1/media"), 2)).status_code == 200
                assert count == 2
                # Queued cancellation must not consume a slot.
                tasks[-1].cancel()
                await asyncio.gather(tasks[-1], return_exceptions=True)
            finally:
                release.set()
                results = await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), 5)
            assert maximum == 2
            assert count == 7
            assert all(r.status_code == 200 for r in results[:-1])
            assert limits.chat_read_limiter().borrowed_tokens == 0

    asyncio.run(run())


def test_sse_read_uses_same_budget_and_disabled_limit(monkeypatch):
    monkeypatch.setattr(limits, "CHAT_READ_CONCURRENCY", 1)

    async def run():
        async with limits.chat_read_slot():
            task = asyncio.create_task(limits.run_chat_read(lambda: 42))
            await asyncio.sleep(.01)
            assert not task.done()
        assert await asyncio.wait_for(task, 2) == 42
        assert limits.chat_read_limiter().borrowed_tokens == 0

    asyncio.run(run())
    monkeypatch.setattr(limits, "CHAT_READ_CONCURRENCY", 0)

    async def disabled():
        assert limits.chat_read_limiter() is None
        assert await limits.run_chat_read(lambda: 7) == 7

    asyncio.run(disabled())
