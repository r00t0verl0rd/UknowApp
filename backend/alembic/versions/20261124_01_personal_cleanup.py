"""Persist personal chat allocation and pending media cleanup."""
import sqlalchemy as sa
from alembic import op

revision = "20261124_01"
down_revision = "20261123_01"
branch_labels = None
depends_on = None


def upgrade():
    # The baseline also bootstraps fresh databases from current metadata.
    tables = sa.inspect(op.get_bind()).get_table_names()
    if "personal_chat_counter" not in tables:
        op.create_table("personal_chat_counter", sa.Column("id", sa.Integer, primary_key=True),
                        sa.Column("last_id", sa.Integer, nullable=False))
    if "personal_media_cleanup" not in tables:
        op.create_table("personal_media_cleanup",
                        sa.Column("conversation_id", sa.Integer, primary_key=True, autoincrement=False))


def downgrade():
    raise RuntimeError("Restore a backup to preserve pending cleanups and reserved identifiers")
