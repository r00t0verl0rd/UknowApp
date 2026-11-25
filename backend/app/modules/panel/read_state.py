"""Compatibility imports for read receipts; use messaging.read_state."""
from app.modules.messaging.read_state import mark_conversation_read, mark_personal_read

__all__ = ["mark_conversation_read", "mark_personal_read"]
