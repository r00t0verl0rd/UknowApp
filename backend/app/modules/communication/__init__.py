"""Общие интерфейсы обмена сообщениями."""

from .contracts import (
    InboundLocation,
    InboundMedia,
    InboundMessage,
    InboundPoll,
    MessageKind,
    MessengerPlatform,
    OutboundMedia,
    OutboundMessage,
)

__all__ = [
    "InboundLocation",
    "InboundMedia",
    "InboundMessage",
    "InboundPoll",
    "MessageKind",
    "MessengerPlatform",
    "OutboundMedia",
    "OutboundMessage",
]
