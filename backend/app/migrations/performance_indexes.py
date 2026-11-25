"""Add hot-path indexes without rewriting business data."""
from sqlalchemy import inspect
from app.models import ConnectorDelivery, ConnectorDeletion, PushSubscription

NAMES = {"ix_push_role_state", "ix_push_session_hash", "ix_connector_delivery_queue",
         "ix_connector_delivery_route_order", "ix_connector_deletion_queue"}


def upgrade_performance_indexes(connection):
    for model in (ConnectorDelivery, ConnectorDeletion, PushSubscription):
        if not inspect(connection).has_table(model.__tablename__):
            continue
        for index in model.__table__.indexes:
            if index.name in NAMES:
                index.create(connection, checkfirst=True)
