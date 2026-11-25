"""Add per-device push diagnostics and session association, preserving subscriptions."""
from sqlalchemy import inspect, text


def upgrade_push_devices(connection):
    inspector = inspect(connection)
    if not inspector.has_table("push_subscriptions"):
        return
    columns = {c["name"] for c in inspector.get_columns("push_subscriptions")}
    timestamp = "TIMESTAMP WITH TIME ZONE" if connection.dialect.name == "postgresql" else "TIMESTAMP"
    for name, typ in (("session_hash", "VARCHAR(64)"), ("revision", "VARCHAR(64)"),
                      ("synced_at", timestamp), ("last_attempt_at", timestamp),
                      ("last_success_at", timestamp), ("delivery_state", "VARCHAR(24)"),
                      ("last_http_status", "INTEGER")):
        if name not in columns:
            connection.execute(text(f"ALTER TABLE push_subscriptions ADD COLUMN {name} {typ}"))
