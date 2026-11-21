"""Thread-safe, bounded SSE notifications for the conversation module."""

import asyncio
import json

_subscribers: dict[asyncio.Queue[str], asyncio.AbstractEventLoop] = {}
_QUEUE_SIZE = 64


def subscribe_chat_updates() -> asyncio.Queue[str]:
    queue: asyncio.Queue[str] = asyncio.Queue(maxsize=_QUEUE_SIZE)
    _subscribers[queue] = asyncio.get_running_loop()
    return queue


def unsubscribe_chat_updates(queue: asyncio.Queue[str]) -> None:
    _subscribers.pop(queue, None)


def _enqueue(queue: asyncio.Queue[str], payload: str) -> None:
    if queue.full():
        while not queue.empty():
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        queue.put_nowait(json.dumps({"resync": True}))
        return
    queue.put_nowait(payload)


def publish_chat_update(
    conversation_id: int,
    conversation_type: str = "conversation",
    message_id: int | None = None,
    action: str = "upsert",
    actor_role: str | None = None,
) -> None:
    payload = json.dumps({
        "conversation_id": int(conversation_id),
        "conversation_type": conversation_type,
        "message_id": int(message_id) if message_id is not None else None,
        "action": action,
        "actor_role": actor_role,
    })
    for queue, loop in tuple(_subscribers.items()):
        try:
            loop.call_soon_threadsafe(_enqueue, queue, payload)
        except RuntimeError:
            _subscribers.pop(queue, None)
