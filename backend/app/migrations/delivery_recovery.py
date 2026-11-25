"""Add nullable recovery timestamps, preserving old jobs."""
from sqlalchemy import inspect, text


def upgrade_delivery_recovery(connection):
    for table in ("connector_deliveries", "connector_deletions"):
        inspector = inspect(connection)
        if not inspector.has_table(table):
            continue
        columns = {c["name"] for c in inspector.get_columns(table)}
        timestamp = "TIMESTAMP WITH TIME ZONE" if connection.dialect.name == "postgresql" else "TIMESTAMP"
        for column, typ in (("published_at", timestamp), ("started_at", timestamp),
                            ("claim_id", "VARCHAR(64)"), ("broker_seq", "BIGINT")):
            if column not in columns:
                connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {typ}"))
