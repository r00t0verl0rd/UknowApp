"""Очистка устаревших данных после миграций."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select, text

from app.core.database import SessionLocal, engine, is_sqlite
from app.models import ConnectionCode, PanelSession, RealtimeEvent


def cleanup_expired_records() -> None:
    # Одноразовые коды и истёкшие сессии не нужны для истории — удаляем старые записи.
    retention_cutoff = datetime.now(UTC) - timedelta(days=30)
    with SessionLocal() as db:
        db.query(PanelSession).filter(PanelSession.expires_at < datetime.now(UTC)).delete(
            synchronize_session=False,
        )
        db.query(ConnectionCode).filter(
            (ConnectionCode.used_at.is_not(None) & (ConnectionCode.used_at < retention_cutoff))
            | (ConnectionCode.expires_at < retention_cutoff),
        ).delete(synchronize_session=False)
        latest = select(func.max(RealtimeEvent.id)).scalar_subquery()
        db.execute(delete(RealtimeEvent).where(RealtimeEvent.id < latest),
                   execution_options={"synchronize_session": False})
        db.commit()

    if is_sqlite:
        with engine.begin() as connection:
            connection.execute(text("PRAGMA optimize"))

