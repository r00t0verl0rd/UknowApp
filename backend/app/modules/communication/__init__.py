"""Messenger-independent communication contracts."""

from .contracts import (
    DeliveryResult,
    InboundMedia,
    InboundMessage,
    MessageKind,
    MessengerAdapter,
    MessengerCapabilities,
    MessengerPlatform,
    OutboundMedia,
    OutboundMessage,
)

__all__ = [
    "DeliveryResult",
    "InboundMedia",
    "InboundMessage",
    "MessageKind",
    "MessengerAdapter",
    "MessengerCapabilities",
    "MessengerPlatform",
    "OutboundMedia",
    "OutboundMessage",
]
