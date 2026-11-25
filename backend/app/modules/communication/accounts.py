"""Привязка пользователей к мессенджерам."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import ConnectionCode, ExternalEndpoint, MessengerAccount, User

from .contracts import MessengerPlatform

CONNECTION_CODE_RE = re.compile(r"^[A-HJ-NP-Z2-9]{8}$")


class MessengerAccountConflict(Exception):
    """Аккаунт мессенджера занят другим пользователем."""


def get_messenger_account(
    db: Session, user_id: int, platform: MessengerPlatform | str,
) -> MessengerAccount | None:
    platform_value = platform.value if isinstance(platform, MessengerPlatform) else platform
    return db.scalar(
        select(MessengerAccount).where(
            MessengerAccount.user_id == user_id,
            MessengerAccount.platform == platform_value,
            MessengerAccount.status == "linked",
        ),
    )


def get_messenger_accounts(
    db: Session,
    user_ids: Iterable[int],
    platform: MessengerPlatform | str,
) -> dict[int, MessengerAccount]:
    """Вернуть привязки адресатов; другие пользователи не требуются."""
    ids = tuple(dict.fromkeys(user_ids))
    if not ids:
        return {}
    platform_value = platform.value if isinstance(platform, MessengerPlatform) else platform
    accounts = db.scalars(
        select(MessengerAccount).where(
            MessengerAccount.user_id.in_(ids),
            MessengerAccount.platform == platform_value,
            MessengerAccount.status == "linked",
        ),
    ).all()
    return {account.user_id: account for account in accounts}


def get_messenger_pair(
    db: Session,
    teacher_id: int,
    student_id: int,
    platform: MessengerPlatform | str,
) -> tuple[MessengerAccount | None, MessengerAccount | None]:
    """Совместимость для кода, которому нужна пара привязок."""
    accounts = get_messenger_accounts(db, (teacher_id, student_id), platform)
    return accounts.get(teacher_id), accounts.get(student_id)


def get_messenger_user(
    db: Session,
    platform: MessengerPlatform | str,
    external_user_id: str | int | None,
) -> User | None:
    if external_user_id is None:
        return None
    platform_value = platform.value if isinstance(platform, MessengerPlatform) else platform
    return db.scalar(
        select(User)
        .join(MessengerAccount, MessengerAccount.user_id == User.id)
        .where(
            MessengerAccount.platform == platform_value,
            MessengerAccount.external_user_id == str(external_user_id),
            MessengerAccount.status == "linked",
        ),
    )


def sync_messenger_account(
    db: Session,
    user_id: int,
    platform: MessengerPlatform | str,
    external_user_id: str | int | None,
    external_chat_id: str | int | None = None,
    username: str | None = None,
) -> MessengerAccount | None:
    """Создать, обновить или удалить привязку аккаунта."""
    platform_value = platform.value if isinstance(platform, MessengerPlatform) else platform
    account = db.scalar(
        select(MessengerAccount).where(
            MessengerAccount.user_id == user_id,
            MessengerAccount.platform == platform_value,
        ),
    )
    if external_user_id is None:
        if account:
            db.delete(account)
        db.execute(delete(ExternalEndpoint).where(ExternalEndpoint.platform == platform_value, ExternalEndpoint.user_id == user_id))
        return None

    normalized_user_id = str(external_user_id).strip()
    if not normalized_user_id:
        raise ValueError("External user ID cannot be empty")
    existing = db.scalar(
        select(MessengerAccount).where(
            MessengerAccount.platform == platform_value,
            MessengerAccount.external_user_id == normalized_user_id,
        ),
    )
    if existing and existing.user_id != user_id:
        raise MessengerAccountConflict(f"{platform_value} identity is already linked")

    if account is not None and account.external_user_id != normalized_user_id:
        db.execute(delete(ExternalEndpoint).where(ExternalEndpoint.platform == platform_value,
                                                 ExternalEndpoint.user_id == user_id))
    account = account or existing
    if account is None:
        account = MessengerAccount(
            user_id=user_id,
            platform=platform_value,
            external_user_id=normalized_user_id,
            linked_at=datetime.now(UTC),
        )
        db.add(account)
    else:
        account.user_id = user_id
        account.platform = platform_value
        account.external_user_id = normalized_user_id
        if account.linked_at is None:
            account.linked_at = datetime.now(UTC)

    if external_chat_id is not None:
        account.external_chat_id = str(external_chat_id)
    elif account.external_chat_id is None:
        account.external_chat_id = normalized_user_id
    if username is not None:
        account.username = username
    account.status = "linked"
    return account


def claim_messenger_connection_code(
    db: Session,
    raw_code: str,
    platform: MessengerPlatform,
    external_user_id: str,
    external_chat_id: str,
    username: str | None = None,
) -> tuple[User | None, str]:
    """Привязать аккаунт по постоянному коду доступа."""
    normalized = re.sub(r"[\s-]", "", raw_code).upper()
    if not CONNECTION_CODE_RE.fullmatch(normalized):
        return None, "invalid_format"

    code_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    connection_code = db.scalar(
        select(ConnectionCode).where(ConnectionCode.code_hash == code_hash),
    )
    if not connection_code:
        return None, "invalid"

    user = db.get(User, connection_code.user_id)
    if not user or user.role not in {"teacher", "student"} or not user.web_password_hash:
        return None, "invalid"

    expires_at = connection_code.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    now = datetime.now(UTC)
    if expires_at <= now:
        return None, "expired"
    if expires_at <= now + timedelta(days=365):
        return None, "invalid"
    if connection_code.used_at is not None:
        return None, "invalid"

    existing_user = get_messenger_user(db, platform, external_user_id)
    if existing_user and existing_user.id != user.id:
        return None, "identity_already_linked"

    existing_account = db.scalar(
        select(MessengerAccount).where(
            MessengerAccount.user_id == user.id,
            MessengerAccount.platform == str(platform),
        ),
    )
    if existing_account and existing_account.external_user_id != str(external_user_id):
        return None, "account_already_linked"

    if platform == MessengerPlatform.TELEGRAM:
        try:
            telegram_id = int(external_user_id)
        except (TypeError, ValueError):
            return None, "invalid"
        # Сохраняем поле старого API для совместимости.
        user.telegram_id = telegram_id

    try:
        sync_messenger_account(
            db, user.id, platform, external_user_id, external_chat_id, username,
        )
        db.commit()
        db.refresh(user)
    except (IntegrityError, MessengerAccountConflict):
        db.rollback()
        return None, "identity_already_linked"
    return user, "ok"


def delete_user_messenger_accounts(db: Session, user_id: int) -> None:
    db.execute(delete(MessengerAccount).where(MessengerAccount.user_id == user_id))
