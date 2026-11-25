"""Auxiliary SQLite store. No business foreign keys or implicit cross-DB transaction."""
import logging
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import ROOT_DIR

logger = logging.getLogger(__name__)
RUNTIME_DIR = ROOT_DIR / "data" / "runtime"
RUNTIME_PATH = RUNTIME_DIR / "runtime.db"


class RuntimeBase(DeclarativeBase):
    pass


# Creating the Engine does not open the file. Core can start if the directory is unavailable.
engine = create_engine("sqlite:///" + str(RUNTIME_PATH),
                       connect_args={"check_same_thread": False, "timeout": .25})


@event.listens_for(engine, "connect")
def configure(connection, _):
    cursor = connection.cursor()
    try:
        cursor.execute("PRAGMA busy_timeout=250")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=FULL")
    finally:
        cursor.close()


RuntimeSessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def initialize_runtime():
    from app import models  # noqa: F401
    RUNTIME_PATH.parent.mkdir(parents=True, exist_ok=True)
    RuntimeBase.metadata.create_all(engine)
