"""Telegram identity compatibility helpers and shared text checks."""

from sqlalchemy.orm import Session

from app.models import User
from app.modules.communication.accounts import get_messenger_user
from app.modules.communication.contracts import MessengerPlatform


def get_linked_user(db: Session, telegram_id: int) -> User | None:
    return get_messenger_user(db, MessengerPlatform.TELEGRAM, telegram_id)
