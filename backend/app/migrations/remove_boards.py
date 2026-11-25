"""Remove the retired interactive boards, not chat or message data."""
from sqlalchemy import text
from app.core.database import engine


def remove_board_tables(connection=None):
    if connection is None:
        with engine.begin() as connection:
            remove_board_tables(connection)
        return
    connection.execute(text("DROP TABLE IF EXISTS graph_objects"))
    connection.execute(text("DROP TABLE IF EXISTS graph_object_deletions"))
