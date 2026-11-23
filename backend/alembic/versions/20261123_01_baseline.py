"""Baseline for the existing application schema (no data deletion).

This first revision bootstraps only missing tables. Existing databases
should already be upgraded by the previous application version before
running it. Future revisions MUST use explicitly reviewed op.* commands.

Revision ID: 20261123_01
Revises:
"""

from alembic import op

from app import models  # noqa: F401 - ensure metadata is populated
from app.core.database import Base

revision = "20261123_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Initial baseline only; do not use dynamic create_all in later revisions.
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    raise RuntimeError("Refusing destructive baseline downgrade; restore from a backup")
