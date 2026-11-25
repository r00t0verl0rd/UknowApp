"""Add nullable recovery timestamps, preserving old jobs."""
from sqlalchemy import inspect, text


def upgrade_delivery_recovery(connection):
    for table in ("connector_deliveries", "connector_deletions"):
        inspector = inspect(connection)
        if not inspector.has_table(table):
            continue
        columns = {c["name"] for c in inspector.get_columns(table)}
        for column, typ in (("published_at", "TIMESTAMP"), ("started_at", "TIMESTAMP"), ("claim_id", "VARCHAR(64)")):
            if column not in columns:
                connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {typ}"))
