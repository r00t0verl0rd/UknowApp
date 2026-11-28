"""Bound SQLite chat reads before consuming a shared HTTP worker or DB connection."""

from contextlib import asynccontextmanager

import anyio
from anyio.lowlevel import RunVar
from fastapi.routing import APIRoute

from .database import is_sqlite, sqlite_int_setting

CHAT_READ_CONCURRENCY = sqlite_int_setting("UKNOWAPP_SQLITE_CHAT_READ_CONCURRENCY", 4, 0, 64) if is_sqlite else 0
# A limiter is local to the running event loop, including independent test clients.
_limiter = RunVar("uknow_chat_read_limiter", default=None)


def chat_read_limiter():
    if not CHAT_READ_CONCURRENCY:
        return None
    limiter = _limiter.get()
    if limiter is None:
        limiter = anyio.CapacityLimiter(CHAT_READ_CONCURRENCY)
        _limiter.set(limiter)
    return limiter


@asynccontextmanager
async def chat_read_slot():
    limiter = chat_read_limiter()
    if limiter is None:
        yield
    else:
        async with limiter:
            yield


async def run_chat_read(function, *args):
    # SSE performs short synchronous SQL work, not the lifetime of the stream.
    async with chat_read_slot():
        return await anyio.to_thread.run_sync(function, *args)


class ChatReadRoute(APIRoute):
    """Gate whole read/sync requests, including auth, response and dependency cleanup."""

    def is_chat_read(self, method):
        if method == "GET":
            return not self.path.endswith("/media")
        return method == "POST" and self.path.endswith(("/sync", "/read"))

    async def handle(self, scope, receive, send):
        if self.is_chat_read(scope.get("method")):
            async with chat_read_slot():
                await super().handle(scope, receive, send)
        else:
            await super().handle(scope, receive, send)
