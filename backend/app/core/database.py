import os

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import DATABASE_URL


class Base(DeclarativeBase):
    pass


# Проверяем соединение перед использованием; для SQLite увеличиваем ожидание блокировки файла БД.
# Для SQLite не делаем лишний SELECT 1 при каждом получении соединения.
# WAL ускоряет параллельное чтение, а NORMAL сохраняет надёжность при меньшем числе fsync.
is_sqlite = DATABASE_URL.startswith("sqlite")
is_file_sqlite = is_sqlite and DATABASE_URL not in {"sqlite://", "sqlite:///:memory:"} and ":memory:" not in DATABASE_URL


def sqlite_int_setting(name, default, minimum, maximum):
    value = int(os.getenv(name, str(default)))
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


engine_options = {"pool_pre_ping": not is_sqlite}
if is_sqlite:
    engine_options["connect_args"] = {"check_same_thread": False, "timeout": 30}
if is_file_sqlite:
    # Preserve the measured SQLAlchemy defaults; tune explicitly for the target VPS.
    engine_options["pool_size"] = sqlite_int_setting("UKNOWAPP_SQLITE_POOL_SIZE", 5, 1, 64)
    engine_options["max_overflow"] = sqlite_int_setting("UKNOWAPP_SQLITE_POOL_OVERFLOW", 10, 0, 64)

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
            if is_file_sqlite:
                cursor.execute("PRAGMA journal_mode=WAL")
        finally:
            cursor.close()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


# Модели и миграции загружаются при запуске приложения.
# Создание таблиц не выполняет миграции существующей схемы.
def create_tables() -> None:
    """Создать таблицы зарегистрированных моделей."""
    Base.metadata.create_all(bind=engine)


def begin_serialized_write(db):
    """Acquire SQLite writer reservation before reading mutable delivery state."""
    if db.get_bind().dialect.name == "sqlite":
        db.connection().exec_driver_sql("BEGIN IMMEDIATE")
