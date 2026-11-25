"""One-way compatibility migration of historical provider records (not runtime models)."""
import json
from sqlalchemy import MetaData, Table, inspect, select, text
from sqlalchemy.orm import Session

from app.core.database import engine
from app.models import ExternalEndpoint, Message, MessengerAccount
from app.bots_gateway.outbox import enqueue_web_delivery
from app.infrastructure.storage.message_metadata import encode_message_metadata
from app.modules.communication.service import record_messenger_delivery
from app.modules.communication.accounts import sync_messenger_account


def migrate_provider_channels(connection=None):
    if connection is None:
        with engine.begin() as connection:
            migrate_provider_channels(connection)
        return
    inspector = inspect(connection)
    tables = set(inspector.get_table_names())
    cols = {col["name"] for col in inspector.get_columns("users")}
    with Session(bind=connection, autoflush=False) as db:
        if "telegram_id" in cols:
            for ident, external_id in connection.execute(text("SELECT id, telegram_id FROM users WHERE telegram_id IS NOT NULL")):
                if db.scalar(select(MessengerAccount).where(MessengerAccount.platform == "telegram",
                              MessengerAccount.user_id == ident)) is None:
                    sync_messenger_account(db, ident, "telegram", str(external_id), str(external_id))
            db.flush()
        if "student_telegram_groups" in tables:
            for user_id, chat, thread in connection.execute(text("SELECT student_id, chat_id, thread_id FROM student_telegram_groups")):
                if db.get(ExternalEndpoint, ("telegram", user_id)) is None and db.scalar(select(MessengerAccount).where(
                    MessengerAccount.platform == "telegram", MessengerAccount.user_id == user_id)) is not None:
                    db.add(ExternalEndpoint(platform="telegram", user_id=user_id, chat_id=str(chat), thread_id=str(thread), preferred=True))
            db.flush()
        if "bot_delivery_jobs" in tables:
            old = Table("bot_delivery_jobs", MetaData(), autoload_with=connection)
            for job in connection.execute(select(old).where(old.c.status.in_(("queued", "processing")))).mappings():
                row = db.get(Message, job["message_id"])
                if row is not None and job["status"] == "queued":
                    enqueue_web_delivery(db, row, ("telegram",))
                elif row is not None:
                    metadata = json.loads(row.metadata_json or "{}")
                    record_messenger_delivery(metadata, "telegram", status="unknown")
                    row.metadata_json = encode_message_metadata(metadata)
                connection.execute(old.update().where(old.c.message_id == job["message_id"]).values(
                    status="migrated" if job["status"] == "queued" else "unknown"))
        db.flush()


def retire_legacy_schema(connection):
    inspector = inspect(connection)
    tables = set(inspector.get_table_names())
    # Legacy delivery identifiers are retained in generic history metadata.
    columns = {c["name"] for c in inspector.get_columns("messages")}
    legacy_cols = [name for name in ("source_message_id", "destination_message_id") if name in columns]
    old = Table("messages", MetaData(), autoload_with=connection)
    for row in connection.execute(select(old.c.id, old.c.metadata_json, *(old.c[k] for k in legacy_cols))).mappings():
        try:
            metadata = json.loads(row["metadata_json"] or "{}")
        except (ValueError, TypeError):
            continue
        if not isinstance(metadata, dict):
            continue
        changed = False
        if "telegram_deliveries" in metadata or "telegram_delivery_errors" in metadata:
            ledgers = metadata.setdefault("messenger_deliveries", {})
            if "telegram" not in ledgers:
                deliveries = metadata.get("telegram_deliveries") or []
                for item in deliveries:
                    item["external_chat_id"] = item.get("external_chat_id") or item.get("chat_id")
                    item["external_message_id"] = item.get("external_message_id") or item.get("telegram_message_id")
                record_messenger_delivery(metadata, "telegram", deliveries, metadata.get("telegram_delivery_errors") or [])
            metadata.pop("telegram_deliveries", None)
            metadata.pop("telegram_delivery_errors", None)
            changed = True
        for key in legacy_cols:
            if row[key] is not None:
                metadata.setdefault("legacy_" + key, str(row[key]))
                changed = True
        if changed:
            connection.execute(old.update().where(old.c.id == row["id"]).values(metadata_json=encode_message_metadata(metadata)))
    for key in legacy_cols:
        connection.execute(text("ALTER TABLE messages DROP COLUMN " + key))
    for table in ("teacher_panels", "teacher_sessions", "student_telegram_groups", "bot_delivery_jobs"):
        if table in tables:
            connection.execute(text("DROP TABLE " + table))
    if "telegram_id" in {c["name"] for c in inspect(connection).get_columns("users")}:
        for index in inspect(connection).get_indexes("users"):
            if "telegram_id" in index["column_names"] and not index.get("duplicates_constraint"):
                name = connection.dialect.identifier_preparer.quote(index["name"])
                connection.execute(text("DROP INDEX " + name))
        connection.execute(text("ALTER TABLE users DROP COLUMN telegram_id"))
