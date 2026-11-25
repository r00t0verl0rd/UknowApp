"""Copy auxiliary rows before retiring their old storage; retry safely after crashes."""
from sqlalchemy import inspect, select, text, MetaData, Table
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from app.core import database, runtime_database
from app.models import PushSubscription, TransportJob, Message


def migrate_push_subscriptions(main_connection, runtime_engine):
    if not inspect(main_connection).has_table("push_subscriptions"):
        return
    # Historical startup migrations have already added all required columns.
    source = main_connection.execute(select(PushSubscription.__table__)).mappings()
    with runtime_engine.begin() as destination:
        for rows in source.partitions(200):
            for row in rows:
                values = dict(row)
                # Endpoint is the actual identity; allocate a fresh numeric id
                # if a partially migrated destination already holds that id.
                values.pop("id", None)
                destination.execute(insert(PushSubscription).values(**values)
                                    .on_conflict_do_nothing(index_elements=["endpoint"]))
    # Only remove the old copy after the auxiliary transaction committed.
    main_connection.execute(text("DROP TABLE push_subscriptions"))


def migrate_transport_state(main_connection, runtime_engine):
    # Only old deployments have publication columns. New deployments never need them.
    for name in ("connector_deliveries", "connector_deletions"):
        inspector = inspect(main_connection)
        columns = {c["name"] for c in inspector.get_columns(name)}
        if not {"published_at", "broker_seq"} & columns:
            continue
        table = Table(name, MetaData(), autoload_with=main_connection)
        source = main_connection.execute(select(table).where(table.c.status.in_(("queued", "published", "sending")))).mappings()
        with runtime_engine.begin() as destination:
            for rows in source.partitions(200):
                message_ids = [row["message_id"] for row in rows if row.get("message_id") is not None]
                kinds = dict(main_connection.execute(select(Message.id, Message.content_type).where(
                    Message.id.in_(message_ids))).all()) if message_ids else {}
                for row in rows:
                    values = dict(id=row["id"], platform=row["platform"], chat_id=row["chat_id"],
                                  thread_id=row.get("thread_id") or "", created_at=row["created_at"],
                                  heavy=kinds.get(row.get("message_id"), "text") != "text",
                                  state="published" if row.get("published_at") else "queued",
                                  published_at=row.get("published_at"), broker_seq=row.get("broker_seq"))
                    destination.execute(insert(TransportJob).values(**values).on_conflict_do_nothing(index_elements=["id"]))
        main_connection.execute(table.update().where(table.c.status == "published").values(status="queued"))
        for column in ("published_at", "broker_seq"):
            if column in columns:
                main_connection.execute(text(f"ALTER TABLE {name} DROP COLUMN {column}"))


def initialize_runtime_storage():
    runtime_database.initialize_runtime()
    # No main write lock on normal startup/retry when all old columns are gone.
    with database.engine.connect() as connection:
        inspector = inspect(connection)
        needs_split = inspector.has_table("push_subscriptions") or any(
            {"published_at", "broker_seq"} & {c["name"] for c in inspector.get_columns(name)}
            for name in ("connector_deliveries", "connector_deletions"))
    if not needs_split:
        return
    with database.engine.begin() as connection:
        if connection.dialect.name == "sqlite":
            connection.exec_driver_sql("BEGIN IMMEDIATE")
        elif connection.dialect.name == "postgresql":
            connection.execute(text("SELECT pg_advisory_xact_lock(672612026)"))
        migrate_push_subscriptions(connection, runtime_database.engine)
        migrate_transport_state(connection, runtime_database.engine)
