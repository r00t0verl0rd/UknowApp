"""Application-owned outbound communication service."""

from __future__ import annotations

from typing import Iterable, Protocol

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

    async def delete_message(
        self, external_chat_id: str, external_message_id: str
    ) -> None:
        ...


class CommunicationService:
    """Dispatch provider-neutral delivery commands to configured adapters."""

    def __init__(
        self, adapters: Iterable[OutboundMessengerAdapter] = ()
    ) -> None:
        self._adapters: dict[MessengerPlatform, OutboundMessengerAdapter] = {}
        for adapter in adapters:
            if adapter.platform in self._adapters:
                raise ValueError(
                    f"Duplicate messenger adapter: {adapter.platform.value}"
                )
            self._adapters[adapter.platform] = adapter

    def has_adapter(self, platform: MessengerPlatform) -> bool:
        return platform in self._adapters

    def _adapter(self, platform: MessengerPlatform) -> OutboundMessengerAdapter:
        adapter = self._adapters.get(platform)
        if adapter is None:
            raise RuntimeError(
                f"No adapter configured for {platform.value}"
            )
        return adapter

    async def send(self, message: OutboundMessage) -> DeliveryResult:
        adapter = self._adapter(message.platform)
        if message.media and not adapter.capabilities.attachments:
            raise NotImplementedError(
                f"{message.platform.value} does not support attachments"
            )
        if not message.media and not adapter.capabilities.text:
            raise NotImplementedError(
                f"{message.platform.value} does not support text messages"
            )
        return await adapter.send(message)

    async def delete_message(
        self,
        platform: MessengerPlatform,
        external_chat_id: str,
        external_message_id: str,
    ) -> None:
        adapter = self._adapter(platform)
        if not adapter.capabilities.delete_messages:
            raise NotImplementedError(
                f"{platform.value} does not support message deletion"
            )
        await adapter.delete_message(
            external_chat_id, external_message_id
        )
