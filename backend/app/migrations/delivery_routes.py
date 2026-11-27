"""Upgrade existing outbox schema without losing pending or completed deliveries."""
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import String, inspect, text


def upgrade_delivery_routes(connection):
    inspector = inspect(connection)
    if not inspector.has_table("connector_deliveries"):
        return
    constraints = inspector.get_unique_constraints("connector_deliveries")
    old = next((c for c in constraints if set(c["column_names"]) ==
                {"message_id", "platform", "recipient_id"}), None)
    if old is None:
        return
    # SQLite считает NULL разными значениями; нормализуем личные адреса.
    connection.execute(text("UPDATE connector_deliveries SET thread_id = '' WHERE thread_id IS NULL"))
    ops = Operations(MigrationContext.configure(connection))
    naming = {"uq": "uq_%(table_name)s_%(column_0_name)s"}
    with ops.batch_alter_table("connector_deliveries", naming_convention=naming) as batch:
        batch.drop_constraint(old["name"] or "uq_connector_deliveries_message_id", type_="unique")
        batch.alter_column("message_id", nullable=True)
        batch.alter_column("thread_id", existing_type=String(255), nullable=False)
        batch.create_unique_constraint("uq_connector_delivery_route",
            ["message_id", "platform", "recipient_id", "chat_id", "thread_id"])
