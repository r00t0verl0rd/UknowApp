from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

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


# Модели и миграции загружаются при запуске приложения.
# Создание таблиц не выполняет миграции существующей схемы.
def create_tables() -> None:
    """Создать таблицы зарегистрированных моделей."""
    Base.metadata.create_all(bind=engine)
