"""Обновление существующей схемы SQLite."""

from sqlalchemy import inspect, text
from app.core.database import engine


def migrate_legacy_schema() -> None:
    # Удаляем временную таблицу сортировки структуры.
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE IF EXISTS graph_positions"))

    # Структура хранит иерархию, старые координаты не нужны.
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE IF EXISTS graph_cloud_positions"))

    # Переносим привязки Telegram, не изменяя пользователей.
    with engine.begin() as connection:
        connection.execute(text(
            """
            INSERT INTO messenger_accounts (
                user_id, platform, external_user_id, external_chat_id, status, linked_at
            )
            SELECT
                users.id,
                'telegram',
                CAST(users.telegram_id AS VARCHAR(255)),
                CAST(users.telegram_id AS VARCHAR(255)),
                'linked',
                NULL
            FROM users
            WHERE users.telegram_id IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1
                  FROM messenger_accounts
                  WHERE messenger_accounts.platform = 'telegram'
                    AND messenger_accounts.user_id = users.id
              )
            """,
        ))

    # Удаляем неиспользуемый признак отключения.
    with engine.begin() as connection:
        user_columns = {column["name"] for column in inspect(connection).get_columns("users")}
        if "active" in user_columns:
            connection.execute(text("ALTER TABLE users DROP COLUMN active"))

    # Сохраняем участников архивных диалогов.
    with engine.connect() as connection:
        conversation_columns = {
            column["name"] for column in inspect(connection).get_columns("conversations")
        }
        if "teacher_id" not in conversation_columns or "student_id" not in conversation_columns:
            connection.commit()
            connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
            connection.commit()
            transaction = connection.begin()
            try:
                connection.exec_driver_sql(
                    "CREATE TABLE conversations_new ("
                    "id INTEGER NOT NULL PRIMARY KEY, "
                    "assignment_id INTEGER UNIQUE REFERENCES assignments(id), "
                    "teacher_id INTEGER NOT NULL REFERENCES users(id), "
                    "student_id INTEGER NOT NULL REFERENCES users(id), "
                    "status VARCHAR(20) NOT NULL, created_at DATETIME NOT NULL)",
                )
                connection.exec_driver_sql(
                    "INSERT INTO conversations_new "
                    "(id, assignment_id, teacher_id, student_id, status, created_at) "
                    "SELECT c.id, c.assignment_id, a.teacher_id, a.student_id, c.status, c.created_at "
                    "FROM conversations c JOIN assignments a ON a.id = c.assignment_id",
                )
                connection.exec_driver_sql("DROP TABLE conversations")
                connection.exec_driver_sql("ALTER TABLE conversations_new RENAME TO conversations")
                transaction.commit()
            except Exception:
                transaction.rollback()
                raise
            finally:
                connection.exec_driver_sql("PRAGMA foreign_keys=ON")

    with engine.begin() as connection:
        connection.execute(text(
            "UPDATE conversations SET assignment_id = NULL "
            "WHERE assignment_id IN (SELECT id FROM assignments WHERE active = 0)",
        ))
        connection.execute(text("DELETE FROM assignments WHERE active = 0"))

    # Ключи запросов исключают дубли при повторной отправке.
    with engine.begin() as connection:
        message_columns = {
            column["name"] for column in inspect(connection).get_columns("messages")
        }
        if "client_message_id" not in message_columns:
            connection.execute(text(
                "ALTER TABLE messages ADD COLUMN client_message_id VARCHAR(64)",
            ))
        for column_name, definition in (
            ("source_platform", "VARCHAR(32)"),
            ("source_event_id", "VARCHAR(255)"),
        ):
            if column_name not in message_columns:
                connection.execute(text(
                    "ALTER TABLE messages ADD COLUMN " + column_name + " " + definition,
                ))
        connection.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_messages_client_message_id "
            "ON messages (conversation_id, sender_id, client_message_id)",
        ))
        connection.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_messages_inbound_event "
            "ON messages (sender_id, source_platform, source_event_id)",
        ))

    # Составной индекс обслуживает историю и счётчики; отдельный индекс по conversation_id избыточен.
    with engine.begin() as connection:
        connection.execute(text("DROP INDEX IF EXISTS ix_messages_conversation_id"))
        connection.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_messages_conversation_created_id "
            "ON messages (conversation_id, created_at, id)",
        ))
        connection.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_messages_conversation_id_id "
            "ON messages (conversation_id, id)",
        ))

    with engine.begin() as connection:
        connection.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_personal_messages_conversation_id_id "
            "ON personal_messages (conversation_id, id)",
        ))

    # Защищаем личные сообщения от повторной записи.
    with engine.begin() as connection:
        columns = {
            column["name"] for column in inspect(connection).get_columns("personal_messages")
        }
        if "client_message_id" not in columns:
            connection.execute(text(
                "ALTER TABLE personal_messages ADD COLUMN client_message_id VARCHAR(64)",
            ))
        connection.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_personal_messages_client_message_id "
            "ON personal_messages (conversation_id, sender_role, client_message_id)",
        ))

    # Метки прочтения личных переписок.
    with engine.begin() as connection:
        columns = {column["name"] for column in inspect(connection).get_columns("personal_messages")}
        for column_name in ("admin_read_at", "participant_read_at"):
            if column_name not in columns:
                connection.execute(text("ALTER TABLE personal_messages ADD COLUMN " + column_name + " DATETIME"))

    user_columns = {column["name"] for column in inspect(engine).get_columns("users")}
    if "web_password_hash" not in user_columns:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE users ADD COLUMN web_password_hash VARCHAR(160)"))

    if "web_username" not in user_columns:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE users ADD COLUMN web_username VARCHAR(160)"))

    if "additional_info" not in user_columns:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE users ADD COLUMN additional_info VARCHAR(500)"))

    # Изначальный логин преподавателя — его имя.
    with engine.begin() as connection:
        connection.execute(text(
            "UPDATE users SET web_username = full_name "
            "WHERE role = 'teacher' AND (web_username IS NULL OR TRIM(web_username) = '')",
        ))

    # Дополняем существующую SQLite-схему при запуске.
    with engine.begin() as connection:
        columns = {
            column["name"]
            for column in inspect(connection).get_columns("teacher_panels")
        }
        migrations = {
            "keyboard_version": "INTEGER NOT NULL DEFAULT 0",
            "keyboard_signature": "VARCHAR(64)",
            "page_index": "INTEGER NOT NULL DEFAULT 0",
        }
        for column_name, definition in migrations.items():
            if column_name not in columns:
                connection.execute(
                    text(
                        "ALTER TABLE teacher_panels ADD COLUMN "
                        + column_name
                        + " "
                        + definition,
                    ),
                )
