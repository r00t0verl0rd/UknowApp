"""Индексированный поиск логина с учётом Unicode."""

from sqlalchemy import inspect, select, text

from app.core.database import SessionLocal, engine
from app.core.security import normalize_login
from app.models import User


def migrate_login_keys() -> None:
    columns = {column["name"] for column in inspect(engine).get_columns("users")}
    with engine.begin() as connection:
        if "web_login_key" not in columns:
            connection.execute(text("ALTER TABLE users ADD COLUMN web_login_key VARCHAR(320)"))
        connection.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_users_web_login_key ON users (web_login_key)"
        ))

    # casefold() корректно нормализует Unicode, включая кириллицу.
    with SessionLocal() as db:
        for user in db.scalars(select(User)).all():
            user.web_login_key = normalize_login(user.web_username or user.full_name)
        db.commit()
