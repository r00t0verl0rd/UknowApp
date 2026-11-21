"""Application-owned outbound communication service.

UknowApp owns message persistence and read state. Messenger adapters only
report delivery to their own external channels.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from .contracts import (
    DeliveryResult,
    MessengerCapabilities,
    MessengerPlatform,
    OutboundMessage,
)


class OutboundMessengerAdapter(Protocol):
    """Provider adapter surface required by outbound application workflows."""

    @property
    def platform(self) -> MessengerPlatform:
        ...

    @property
    def capabilities(self) -> MessengerCapabilities:
        ...

    async def send(self, message: OutboundMessage) -> DeliveryResult:
        ...


class CommunicationService:
    """Registry and dispatcher for independently enabled messenger adapters."""

    def __init__(
        self, adapters: Iterable[OutboundMessengerAdapter] = (),
    ) -> None:
        self._adapters: dict[MessengerPlatform, OutboundMessengerAdapter] = {}
        for adapter in adapters:
            self.register(adapter)

    @property
    def platforms(self) -> tuple[MessengerPlatform, ...]:
        """Return only channels whose adapters are currently enabled."""
        return tuple(self._adapters)

    def register(self, adapter: OutboundMessengerAdapter) -> None:
        """Register one optional provider without coupling it to other providers."""
        platform = adapter.platform
        if platform in self._adapters:
            raise ValueError(f"Duplicate messenger adapter: {platform.value}")
        self._adapters[platform] = adapter

    def has_adapter(self, platform: MessengerPlatform) -> bool:
        return platform in self._adapters

    def _adapter(self, platform: MessengerPlatform) -> OutboundMessengerAdapter:
        adapter = self._adapters.get(platform)
        if adapter is None:
            raise RuntimeError(f"No adapter configured for {platform.value}")
        return adapter

    async def send(self, message: OutboundMessage) -> DeliveryResult:
        adapter = self._adapter(message.platform)
        if message.media and not adapter.capabilities.attachments:
            raise NotImplementedError(
                f"{message.platform.value} does not support attachments",
            )
        if not message.media and not adapter.capabilities.text:
            raise NotImplementedError(
                f"{message.platform.value} does not support text messages",
            )
        return await adapter.send(message)

    async def delete_message(
        self,
        platform: MessengerPlatform,
        external_chat_id: str,
        external_message_id: str,
    ) -> None:
        adapter = self._adapter(platform)
        delete = getattr(adapter, "delete_message", None)
        if not adapter.capabilities.delete_messages or delete is None:
            raise NotImplementedError(
                f"{platform.value} does not support message deletion",
            )
        await delete(external_chat_id, external_message_id)


def record_messenger_delivery(
    metadata: dict,
    platform: MessengerPlatform | str,
    delivered: Iterable[dict] = (),
    errors: Iterable[dict] = (),
    status: str | None = None,
) -> None:
    """Record provider delivery separately from UknowApp message delivery."""
    platform_value = platform.value if isinstance(platform, MessengerPlatform) else str(platform)
    delivered_items = [dict(item) for item in delivered]
    error_items = [dict(item) for item in errors]

    if status is None:
        status = (
            "delivered" if delivered_items and not error_items
            else "partial" if delivered_items
            else "failed" if error_items
            else "not_connected"
        )

    channels = metadata.setdefault("messenger_deliveries", {})
    channels[platform_value] = {
        "status": status,
        "delivered": delivered_items,
        "errors": error_items,
    }

    # Keep the old Telegram keys during the transition so existing group-topic
    # routing and delete operations continue to work for historical messages.
    if platform_value == MessengerPlatform.TELEGRAM.value:
        metadata["telegram_deliveries"] = [
            {
                "user_id": item.get("user_id"),
                "telegram_message_id": item.get("external_message_id"),
                "chat_id": item.get("external_chat_id"),
                "thread_id": item.get("external_thread_id"),
            }
            for item in delivered_items
        ]
        if error_items:
            metadata["telegram_delivery_errors"] = error_items
        else:
            metadata.pop("telegram_delivery_errors", None)
