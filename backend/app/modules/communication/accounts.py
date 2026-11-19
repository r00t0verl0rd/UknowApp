"""Persistence helpers for external messenger account bindings."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ...models import MessengerAccount
from .contracts import MessengerPlatform


class MessengerAccountConflict(Exception):
    """Raised when an external identity is already owned by another user."""


def sync_messenger_account(
    db: Session,
    user_id: int,
    platform: MessengerPlatform | str,
    external_user_id: str | int | None,
    external_chat_id: str | int | None = None,
    username: str | None = None,
) -> MessengerAccount | None:
    """Create or update one platform identity, or remove it when ID is None."""
    platform_value = platform.value if isinstance(platform, MessengerPlatform) else platform
    account = db.scalar(
        select(MessengerAccount).where(
            MessengerAccount.user_id == user_id,
            MessengerAccount.platform == platform_value,
        )
    )

    if external_user_id is None:
        if account:
            db.delete(account)
        return None

    normalized_user_id = str(external_user_id).strip()
    if not normalized_user_id:
        raise ValueError("External user ID cannot be empty")

    existing = db.scalar(
        select(MessengerAccount).where(
            MessengerAccount.platform == platform_value,
            MessengerAccount.external_user_id == normalized_user_id,
        )
    )
    if existing and existing.user_id != user_id:
        raise MessengerAccountConflict(
            f"{platform_value} identity is already linked"
        )

    account = account or existing
    now = datetime.now(timezone.utc)
    if account is None:
        account = MessengerAccount(
            user_id=user_id,
            platform=platform_value,
            external_user_id=normalized_user_id,
            linked_at=now,
        )
        db.add(account)
    else:
        account.user_id = user_id
        account.platform = platform_value
        account.external_user_id = normalized_user_id
        if account.linked_at is None:
            account.linked_at = now

    if external_chat_id is not None:
        account.external_chat_id = str(external_chat_id)
    elif account.external_chat_id is None:
        account.external_chat_id = normalized_user_id
    if username is not None:
        account.username = username
    account.status = "linked"
    return account


def delete_user_messenger_accounts(db: Session, user_id: int) -> None:
    """Remove all provider identities before their owning user is deleted."""
    db.execute(
        delete(MessengerAccount).where(MessengerAccount.user_id == user_id)
    )
