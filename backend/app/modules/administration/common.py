"""Administration: common."""

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
from pathlib import Path, PurePosixPath
from typing import Annotated

from fastapi import Depends, HTTPException

from app.core.database import SessionLocal, engine
from app.infrastructure.storage.media import MEDIA_DIR
from app.modules.auth.service import require_admin

Admin = Annotated[str, Depends(require_admin)]

DATA_DIR = MEDIA_DIR.parent.resolve()
PENDING_RESTORE_NAME = ".uknowapp-restore-pending.json"
RESTORE_RESULT_NAME = ".uknowapp-restore-result.json"
RESTORE_STAGE_PREFIX = ".uknowapp-restore-stage-"
RESTORE_BACKUP_PREFIX = ".uknowapp-restore-backup-"
RESTORE_UPLOAD_LOCK = ".uknowapp-restore-upload.lock"
INTERNAL_PREFIX = ".uknowapp-"

MAX_ARCHIVE_ENTRIES = 100000
FULL_BACKUP_FORMAT = "uknowapp-full-backup-v2"


def get_db():
    with SessionLocal() as db:
        yield db

def database_path() -> Path:
    if engine.dialect.name != "sqlite" or not engine.url.database:
        raise HTTPException(status_code=501, detail="Резервное копирование доступно для SQLite")
    return Path(engine.url.database).resolve()


def database_relative_path(data_dir: Path | None = None) -> Path:
    root = (data_dir or DATA_DIR).resolve()
    try:
        relative = database_path().relative_to(root)
    except ValueError as exc:
        raise HTTPException(
            status_code=501,
            detail="Файл SQLite должен находиться внутри каталога data",
        ) from exc
    if not relative.parts or any(part.startswith(INTERNAL_PREFIX) for part in relative.parts):
        raise HTTPException(status_code=400, detail="Недопустимый путь к базе данных")
    return relative


def temporary_path(prefix: str, suffix: str, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=prefix, suffix=suffix, dir=directory)
    os.close(descriptor)
    return Path(name)


def remove_temp(path: str) -> None:
    Path(path).unlink(missing_ok=True)


def remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.is_dir():
        shutil.rmtree(path, ignore_errors=False)


def folder_size(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def safe_relative(value: str) -> Path:
    if (
        not isinstance(value, str)
        or not value
        or "\\" in value
        or "\x00" in value
        or value.startswith("/")
        or value.endswith("/")
        or "//" in value
    ):
        raise HTTPException(status_code=400, detail="Архив содержит недопустимый путь")
    candidate = PurePosixPath(value)
    if candidate.is_absolute() or not candidate.parts or any(
        part in {"", ".", ".."} for part in candidate.parts
    ):
        raise HTTPException(status_code=400, detail="Архив содержит недопустимый путь")
    return Path(*candidate.parts)


def safe_data_entry(value: str) -> Path:
    relative = safe_relative(value)
    if len(relative.parts) < 2 or relative.parts[0] != "data":
        raise HTTPException(status_code=400, detail="В архиве обнаружен файл вне каталога data")
    if relative.parts[1].startswith(INTERNAL_PREFIX) or value != relative.as_posix():
        raise HTTPException(status_code=400, detail="Недопустимый путь файла данных")
    return Path(*relative.parts[1:])


def require_backup_space(directory: Path, required: int) -> None:
    # Оставляем место для БД и параллельных запросов.
    if shutil.disk_usage(directory).free < required + 256 * 1024 * 1024:
        raise HTTPException(status_code=507, detail="Недостаточно свободного места для резервной копии")


def hash_file(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            size += len(chunk)
            digest.update(chunk)
    return size, digest.hexdigest()


def count_missing_media_references(database: Path, data_root: Path) -> int:
    missing = 0
    media_root = (data_root / "media").resolve()
    attachment_types = {"photo", "video", "audio", "voice", "document", "animation", "sticker", "video_note"}
    with sqlite3.connect(database.as_uri() + "?mode=ro&immutable=1", uri=True) as connection:
        for table in ("messages", "personal_messages"):
            columns = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
            if "metadata_json" not in columns:
                continue
            # В таблицах и названиях столбцов используем только проверенные SQL-литералы.
            query = {
                ("messages", True): "SELECT metadata_json, content_type FROM messages",
                ("messages", False): "SELECT metadata_json, NULL FROM messages",
                ("personal_messages", True): "SELECT metadata_json, content_type FROM personal_messages",
                ("personal_messages", False): "SELECT metadata_json, NULL FROM personal_messages",
            }[(table, "content_type" in columns)]
            for raw, content_type in connection.execute(query):
                try:
                    metadata = json.loads(raw or "{}")
                except (TypeError, ValueError):
                    metadata = None
                # Старые сообщения могут содержать некорректные метаданные без файла.
                if not isinstance(metadata, dict):
                    if content_type in attachment_types:
                        missing += 1
                    continue
                try:
                    media = metadata.get("media")
                    if media is None and content_type not in attachment_types:
                        continue
                    if not isinstance(media, dict) or media.get("archive_status") != "stored":
                        missing += 1
                        continue
                    target = (media_root / safe_relative(media.get("local_path"))).resolve()
                    size = media.get("file_size")
                    if (
                        media_root not in target.parents
                        or not target.is_file()
                        or (size is not None and target.stat().st_size != size)
                    ):
                        missing += 1
                    else:
                        with target.open("rb") as file:
                            file.read(1)
                except (HTTPException, AttributeError, TypeError, ValueError, OSError):
                    missing += 1
    return missing


def require_complete_media(database: Path, root: Path) -> None:
    missing = count_missing_media_references(database, root)
    if missing:
        raise HTTPException(409, f"Нечитаемые или отсутствующие медиафайлы: {missing}. Проверьте вложения обеих групп переписок.")


def validate_database(path: Path) -> None:
    try:
        with sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True) as uploaded:
            integrity = uploaded.execute("PRAGMA integrity_check").fetchone()
            foreign_key_error = uploaded.execute("PRAGMA foreign_key_check").fetchone()
            tables = {
                row[0]
                for row in uploaded.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'",
                )
            }
    except sqlite3.Error as exc:
        raise HTTPException(
            status_code=400,
            detail="Не удалось прочитать базу данных в резервной копии",
        ) from exc
    if (
        not integrity
        or integrity[0] != "ok"
        or foreign_key_error is not None
        or not {"users", "messages", "conversations"}.issubset(tables)
    ):
        raise HTTPException(
            status_code=400,
            detail="Архив не содержит корректную базу данных UknowApp",
        )
