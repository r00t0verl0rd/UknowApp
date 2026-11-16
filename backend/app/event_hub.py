"""In-process notifications for live panel updates.

The application runs a single Uvicorn worker because Telegram long polling
must have a single owner. A bounded queue per SSE client coalesces bursts:
clients only need to know that some panel data changed and should be reloaded.
"""

import asyncio
import json


_subscribers: set[asyncio.Queue[str]] = set()


def subscribe_chat_updates() -> asyncio.Queue:
    queue = asyncio.Queue(maxsize=1)
    _subscribers.add(queue)
    return queue


def unsubscribe_chat_updates(queue: asyncio.Queue) -> None:
    _subscribers.discard(queue)


def publish_chat_update(conversation_id: int) -> None:
    payload = json.dumps({"conversation_id": int(conversation_id)})
    for queue in tuple(_subscribers):
        if queue.full():
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        try:
            queue.put_nowait(payload)
        except asyncio.QueueFull:
            # A notification is only an invalidation signal; a later update
            # or the client's reconnect will trigger a fresh authoritative read.
            pass
