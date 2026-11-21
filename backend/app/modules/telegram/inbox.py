"""Durable inbound Telegram update inbox (primary UknowApp SQLite database).

Only the primary backend owns this table. The gateway accepts a Telegram
update only after writing it into its own durable spool; the primary accepts
an update only after writing it into this inbox. Workers process independently.
"""
from datetime import UTC, datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class TelegramUpdate(Base):
    __tablename__ = "telegram_inbound_updates"

    update_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    payload: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
