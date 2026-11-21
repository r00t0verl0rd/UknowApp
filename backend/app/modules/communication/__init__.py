"""Общие интерфейсы обмена сообщениями."""

from .contracts import (
    DeliveryResult,
    InboundLocation,
    InboundMedia,
    InboundMessage,
    InboundPoll,
    MessageKind,
    MessengerAdapter,
    MessengerCapabilities,
    MessengerPlatform,
    OutboundMedia,
    OutboundMessage,
)

__all__ = [
    "DeliveryResult",
    "InboundLocation",
    "InboundMedia",
    "InboundMessage",
    "InboundPoll",
    "MessageKind",
    "MessengerAdapter",
    "MessengerCapabilities",
    "MessengerPlatform",
    "OutboundMedia",
    "OutboundMessage",
]
