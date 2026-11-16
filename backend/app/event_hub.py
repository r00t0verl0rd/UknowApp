"""Локальные уведомления для обновления веб-панели в реальном времени.

Приложение работает с одним Uvicorn worker, чтобы только один процесс
управлял Telegram long polling. Ограниченная очередь SSE-клиента объединяет
частые события: браузеру достаточно узнать, что данные изменились, и перечитать их.
"""

import asyncio
import json


_subscribers: set[asyncio.Queue[str]] = set()


# Создаём очередь на одного клиента; размер 1 не даёт копить устаревшие события.
def subscribe_chat_updates() -> asyncio.Queue:
    queue = asyncio.Queue(maxsize=1)
    _subscribers.add(queue)
    return queue


def unsubscribe_chat_updates(queue: asyncio.Queue) -> None:
    _subscribers.discard(queue)


# Отправляем сигнал об изменении, а не сами данные: источником истины остаётся БД.
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
