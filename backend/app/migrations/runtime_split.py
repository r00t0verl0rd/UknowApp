"""Copy auxiliary rows before retiring their old storage; retry safely after crashes."""
from sqlalchemy import inspect, select, text
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from app.core import database, runtime_database
from app.models import PushSubscription


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


def initialize_runtime_storage():
    runtime_database.initialize_runtime()
    with database.engine.begin() as connection:
        if connection.dialect.name == "sqlite":
            connection.exec_driver_sql("BEGIN IMMEDIATE")
        elif connection.dialect.name == "postgresql":
            connection.execute(text("SELECT pg_advisory_xact_lock(672612026)"))
        migrate_push_subscriptions(connection, runtime_database.engine)
