"""Telegram identity compatibility helpers and shared text checks."""

from sqlalchemy.orm import Session

from ...models import User
from ..communication.accounts import get_messenger_user
from ..communication.contracts import MessengerPlatform
from ..messaging.moderation import text_contains_contact_data


def get_linked_user(db: Session, telegram_id: int) -> User | None:
    return get_messenger_user(db, MessengerPlatform.TELEGRAM, telegram_id)
