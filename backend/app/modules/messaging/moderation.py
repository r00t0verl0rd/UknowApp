"""Модуль модерации отключён. Оставлен как совместимая заглушка."""

from app.modules.communication.contracts import InboundMessage


def text_contains_contact_data(body: str) -> bool:
    """Не блокирует текстовые сообщения: модерация отключена."""
    return False


def contact_would_be_exposed(message: InboundMessage) -> bool:
    """Не блокирует входящие сообщения: модерация отключена."""
    return False
