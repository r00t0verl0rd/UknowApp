"""Indexed Unicode login lookup for historical schemas."""
from sqlalchemy import inspect, text

from app.core.database import engine
from app.core.security import normalize_login


def migrate_login_keys(connection=None):
    if connection is None:
        with engine.begin() as connection:
            migrate_login_keys(connection)
        return
    columns = {column["name"] for column in inspect(connection).get_columns("users")}
    if "web_login_key" not in columns:
        connection.execute(text("ALTER TABLE users ADD COLUMN web_login_key VARCHAR(320)"))
    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_users_web_login_key ON users (web_login_key)"))
    # Use historical scalar columns, not current ORM projections.
    for row in connection.execute(text("SELECT id, web_username, full_name FROM users")).mappings():
        connection.execute(text("UPDATE users SET web_login_key=:key WHERE id=:id"),
                           {"key": normalize_login(row["web_username"] or row["full_name"]), "id": row["id"]})
