from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from datetime import datetime, timedelta, timezone

from .config import DATABASE_URL


class Base(DeclarativeBase):
    pass


# Проверяем соединение перед использованием; для SQLite увеличиваем ожидание блокировки файла БД.
# Для SQLite не делаем лишний SELECT 1 при каждом получении соединения.
# WAL ускоряет параллельное чтение, а NORMAL сохраняет надёжность при меньшем числе fsync.
is_sqlite = DATABASE_URL.startswith("sqlite")
engine_options = {"pool_pre_ping": not is_sqlite}
if is_sqlite:
    engine_options["connect_args"] = {"check_same_thread": False, "timeout": 30}

engine = create_engine(DATABASE_URL, **engine_options)

if is_sqlite:
    @event.listens_for(engine, "connect")
    def configure_sqlite_connection(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA temp_store=MEMORY")
            # WAL не применяется к in-memory SQLite и не подходит для сетевых файловых систем.
            if DATABASE_URL not in {"sqlite://", "sqlite:///:memory:"} and ":memory:" not in DATABASE_URL:
                cursor.execute("PRAGMA journal_mode=WAL")
        finally:
            cursor.close()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


# Создаём таблицы и выполняем небольшие совместимые миграции старых баз данных.
def create_tables() -> None:
    # Импорт моделей регистрирует все таблицы в Base.metadata.
    from .models import ConnectionCode, PanelSession, PersonalConversation, PersonalMessage

    Base.metadata.create_all(bind=engine)

    # Archived conversations retain participant IDs without keeping obsolete assignments.
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
                    "status VARCHAR(20) NOT NULL, created_at DATETIME NOT NULL)"
                )
                connection.exec_driver_sql(
                    "INSERT INTO conversations_new "
                    "(id, assignment_id, teacher_id, student_id, status, created_at) "
                    "SELECT c.id, c.assignment_id, a.teacher_id, a.student_id, c.status, c.created_at "
                    "FROM conversations c JOIN assignments a ON a.id = c.assignment_id"
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
            "WHERE assignment_id IN (SELECT id FROM assignments WHERE active = 0)"
        ))
        connection.execute(text("DELETE FROM assignments WHERE active = 0"))

    # Составной индекс обслуживает историю и счётчики; отдельный индекс по conversation_id избыточен.
    with engine.begin() as connection:
        connection.execute(text("DROP INDEX IF EXISTS ix_messages_conversation_id"))
        connection.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_messages_conversation_created_id "
            "ON messages (conversation_id, created_at, id)"
        ))

    # Read markers for private in-app conversations.
    with engine.begin() as connection:
        columns = {column["name"] for column in inspect(connection).get_columns("personal_messages")}
        for column_name in ("admin_read_at", "participant_read_at"):
            if column_name not in columns:
                connection.execute(text("ALTER TABLE personal_messages ADD COLUMN " + column_name + " DATETIME"))

    # Одноразовые коды и истёкшие сессии не нужны для истории — удаляем старые записи.
    retention_cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    with SessionLocal() as db:
        db.query(PanelSession).filter(PanelSession.expires_at < datetime.now(timezone.utc)).delete(
            synchronize_session=False
        )
        db.query(ConnectionCode).filter(
            (ConnectionCode.used_at.is_not(None) & (ConnectionCode.used_at < retention_cutoff))
            | (ConnectionCode.expires_at < retention_cutoff)
        ).delete(synchronize_session=False)
        db.commit()

    if is_sqlite:
        with engine.begin() as connection:
            connection.execute(text("PRAGMA optimize"))

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

    # Existing teachers receive their current full name as the initial web login.
    with engine.begin() as connection:
        connection.execute(text(
            "UPDATE users SET web_username = full_name "
            "WHERE role = 'teacher' AND (web_username IS NULL OR TRIM(web_username) = '')"
        ))

    # create_all does not add columns to an existing database. Keep this small,
    # idempotent migration here so existing local SQLite installs are upgraded
    # automatically when the backend starts.
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
                        + definition
                    )
                )
