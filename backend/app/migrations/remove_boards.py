"""Одноразовая очистка данных удалённого модуля интерактивных досок."""

from sqlalchemy import text

from app.core.database import engine


def remove_board_tables() -> None:
    """Удалить устаревшие таблицы досок вместе с содержимым."""
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE IF EXISTS graph_objects"))
        connection.execute(text("DROP TABLE IF EXISTS graph_object_deletions"))
