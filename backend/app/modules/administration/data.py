"""Администрирование данных, резервное копирование и перенос всего каталога data."""

import contextlib
import hashlib
import json
import logging
import os
import shutil
import signal
import sqlite3
import stat
import tempfile
import uuid
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from app.core.database import SessionLocal, engine
from app.event_hub import publish_chat_update
from app.infrastructure.storage.database_info import database_storage_info
from app.infrastructure.storage.media import MEDIA_DIR, delete_message_media
from app.models import (
    Assignment,
    ConnectionCode,
    Conversation,
    Message,
    PanelSession,
    PersonalConversation,
    PersonalMessage,
    StudentTelegramGroup,
    TeacherPanel,
    TeacherSession,
    User,
)
from app.modules.auth.service import require_admin

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin/data", tags=["admin-data"])
Admin = Annotated[str, Depends(require_admin)]


def _get_db():
    with SessionLocal() as db:
        yield db

DATA_DIR = MEDIA_DIR.parent.resolve()
PENDING_RESTORE_NAME = ".uknowapp-restore-pending.json"
RESTORE_RESULT_NAME = ".uknowapp-restore-result.json"
RESTORE_STAGE_PREFIX = ".uknowapp-restore-stage-"
RESTORE_BACKUP_PREFIX = ".uknowapp-restore-backup-"
RESTORE_UPLOAD_LOCK = ".uknowapp-restore-upload.lock"
INTERNAL_PREFIX = ".uknowapp-"

MAX_ARCHIVE_ENTRIES = 100000
FULL_BACKUP_FORMAT = "uknowapp-full-backup-v2"


def _database_path() -> Path:
    if engine.dialect.name != "sqlite" or not engine.url.database:
        raise HTTPException(status_code=501, detail="Резервное копирование доступно для SQLite")
    return Path(engine.url.database).resolve()


def _database_relative_path(data_dir: Path | None = None) -> Path:
    root = (data_dir or DATA_DIR).resolve()
    try:
        relative = _database_path().relative_to(root)
    except ValueError as exc:
        raise HTTPException(
            status_code=501,
            detail="Файл SQLite должен находиться внутри каталога data",
        ) from exc
    if not relative.parts or any(part.startswith(INTERNAL_PREFIX) for part in relative.parts):
        raise HTTPException(status_code=400, detail="Недопустимый путь к базе данных")
    return relative


def _temporary_path(prefix: str, suffix: str, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=prefix, suffix=suffix, dir=directory)
    os.close(descriptor)
    return Path(name)


def _remove_temp(path: str) -> None:
    Path(path).unlink(missing_ok=True)


def _remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.is_dir():
        shutil.rmtree(path, ignore_errors=False)


def _folder_size(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def _safe_relative(value: str) -> Path:
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


def _safe_data_entry(value: str) -> Path:
    relative = _safe_relative(value)
    if len(relative.parts) < 2 or relative.parts[0] != "data":
        raise HTTPException(status_code=400, detail="В архиве обнаружен файл вне каталога data")
    if relative.parts[1].startswith(INTERNAL_PREFIX) or value != relative.as_posix():
        raise HTTPException(status_code=400, detail="Недопустимый путь файла данных")
    return Path(*relative.parts[1:])


def _require_backup_space(directory: Path, required: int) -> None:
    # Оставляем место для БД и параллельных запросов.
    if shutil.disk_usage(directory).free < required + 256 * 1024 * 1024:
        raise HTTPException(status_code=507, detail="Недостаточно свободного места для резервной копии")


def _create_database_snapshot(destination: Path) -> None:
    database = _database_path()
    if not database.is_file():
        raise HTTPException(status_code=404, detail="Файл базы данных не найден")
    _require_backup_space(destination.parent, database.stat().st_size)
    with sqlite3.connect(database) as source, sqlite3.connect(destination) as target:
        source.backup(target)


def _iter_data_files(data_dir: Path, database: Path):
    root = data_dir.resolve()
    database = database.resolve()
    sidecars = {
        Path(str(database) + "-wal"),
        Path(str(database) + "-shm"),
        Path(str(database) + "-journal"),
    }
    for current, directory_names, file_names in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        if current_path == root:
            directory_names[:] = [
                name for name in directory_names
                if not name.startswith(INTERNAL_PREFIX)
            ]
        for name in tuple(directory_names):
            candidate = current_path / name
            if candidate.is_symlink():
                raise HTTPException(
                    status_code=400,
                    detail="В каталоге data обнаружена символическая ссылка; перенесите её содержимое в обычный файл или каталог",
                )
        for name in file_names:
            source = current_path / name
            if name.startswith(INTERNAL_PREFIX):
                continue
            if source.is_symlink():
                raise HTTPException(
                    status_code=400,
                    detail="В каталоге data обнаружена символическая ссылка; перенесите её содержимое в обычный файл или каталог",
                )
            if not source.is_file() or source.resolve() == database or source.resolve() in sidecars:
                continue
            yield source, source.relative_to(root)


def _hash_file(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            size += len(chunk)
            digest.update(chunk)
    return size, digest.hexdigest()


def _count_missing_media_references(database: Path, data_root: Path) -> int:
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
                # Old text messages can carry JSON null, arrays, strings or
                # invalid metadata. They do not refer to missing media.
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
                    target = (media_root / _safe_relative(media.get("local_path"))).resolve()
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


def _require_complete_media(database: Path, root: Path) -> None:
    missing = _count_missing_media_references(database, root)
    if missing:
        raise HTTPException(409, f"Нечитаемые или отсутствующие медиафайлы: {missing}. Проверьте вложения обеих групп переписок.")


def _validate_database(path: Path) -> None:
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


def _build_full_backup(archive_path: Path, staging_root: Path) -> dict:
    data_dir = DATA_DIR.resolve()
    database = _database_path()
    database_relative = _database_relative_path(data_dir)
    if not data_dir.is_dir():
        raise HTTPException(status_code=404, detail="Каталог data не найден")

    staged_data = staging_root / "data"
    staged_data.mkdir(parents=True)
    for source, relative in _iter_data_files(data_dir, database):
        target = staged_data / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        _require_backup_space(target.parent, source.stat().st_size)
        shutil.copy2(source, target)

    staged_database = staged_data / database_relative
    staged_database.parent.mkdir(parents=True, exist_ok=True)
    _create_database_snapshot(staged_database)
    _validate_database(staged_database)

    file_records = []
    total_unpacked = 0
    staged_files = sorted(path for path in staged_data.rglob("*") if path.is_file())
    if len(staged_files) > MAX_ARCHIVE_ENTRIES:
        raise HTTPException(status_code=413, detail="В каталоге data слишком много файлов")
    for path in staged_files:
        relative = path.relative_to(staged_data).as_posix()
        size, checksum = _hash_file(path)
        total_unpacked += size
        file_records.append({
            "path": "data/" + relative,
            "size": size,
            "sha256": checksum,
        })

    _require_complete_media(staged_database, staged_data)
    manifest = {
        "format": FULL_BACKUP_FORMAT,
        "format_version": 2,
        "app_version": "0.1.0",
        "created_at": datetime.now(UTC).isoformat(),
        "database_path": database_relative.as_posix(),
        "files": file_records,
        "file_count": len(file_records),
        "unpacked_bytes": total_unpacked,
        "missing_media_references": 0,
    }
    manifest_json = json.dumps(manifest, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(manifest_json) > 64 * 1024 * 1024:
        raise HTTPException(413, detail="Слишком большой служебный manifest.json")
    _require_backup_space(archive_path.parent, total_unpacked + len(manifest_json))
    with zipfile.ZipFile(
        archive_path,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=1,
    ) as archive:
        for path in staged_files:
            relative = path.relative_to(staged_data).as_posix()
            compression = (
                zipfile.ZIP_STORED
                if relative.startswith("media/")
                else zipfile.ZIP_DEFLATED
            )
            archive.write(
                path,
                "data/" + relative,
                compress_type=compression,
            )
        archive.writestr(
            "manifest.json",
            manifest_json,
        )
    return manifest


def _validate_archive_entries(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    entries = archive.infolist()
    if len(entries) > MAX_ARCHIVE_ENTRIES + 1:
        raise HTTPException(status_code=413, detail="В архиве слишком много файлов")
    names = [item.filename for item in entries]
    if len(names) != len(set(names)):
        raise HTTPException(status_code=400, detail="Архив содержит повторяющиеся имена файлов")
    for item in entries:
        mode = item.external_attr >> 16
        if stat.S_ISLNK(mode):
            raise HTTPException(status_code=400, detail="Символические ссылки в архиве запрещены")
        if item.is_dir():
            raise HTTPException(status_code=400, detail="Архив должен содержать только файлы")
    return entries


def _read_archive_manifest(archive: zipfile.ZipFile) -> dict:
    try:
        if archive.getinfo("manifest.json").file_size > 64 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="Слишком большой служебный manifest.json")
        manifest = json.loads(archive.read("manifest.json"))
    except (KeyError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=400, detail="В архиве отсутствует корректный manifest.json") from exc
    if not isinstance(manifest, dict):
        raise HTTPException(status_code=400, detail="Некорректный manifest.json")
    return manifest


def _extract_v2_archive(
    archive: zipfile.ZipFile,
    entries: list[zipfile.ZipInfo],
    manifest: dict,
    staged_data: Path,
    expected_database: Path,
) -> int:
    if manifest.get("format") != FULL_BACKUP_FORMAT or manifest.get("format_version") != 2:
        raise HTTPException(status_code=400, detail="Версия полной резервной копии не поддерживается")
    database_relative = _safe_relative(manifest.get("database_path", ""))
    if any(part.startswith(INTERNAL_PREFIX) for part in database_relative.parts):
        raise HTTPException(400, "Недопустимый путь к базе данных в архиве")

    records = manifest.get("files")
    if not isinstance(records, list) or not records or len(records) > MAX_ARCHIVE_ENTRIES:
        raise HTTPException(status_code=400, detail="В manifest отсутствует список файлов data")
    if any(
        not isinstance(item, dict)
        or type(item.get("size")) is not int
        or item["size"] < 0
        for item in records
    ):
        raise HTTPException(status_code=400, detail="Некорректный размер файла в manifest")
    declared_file_count = manifest.get("file_count")
    declared_unpacked_bytes = manifest.get("unpacked_bytes")
    declared_total = sum(item["size"] for item in records)
    if (
        type(declared_file_count) is not int
        or declared_file_count != len(records)
        or type(declared_unpacked_bytes) is not int
        or declared_unpacked_bytes != declared_total
    ):
        raise HTTPException(status_code=400, detail="Счётчики файлов в manifest не совпадают")
    record_map = {}
    for record in records:
        if not isinstance(record, dict):
            raise HTTPException(status_code=400, detail="Некорректная запись файла в manifest")
        archive_name = record.get("path")
        relative = _safe_data_entry(archive_name)
        size = record.get("size")
        checksum = record.get("sha256")
        if (
            type(size) is not int
            or size < 0
            or not isinstance(checksum, str)
            or len(checksum) != 64
            or any(char not in "0123456789abcdef" for char in checksum.lower())
        ):
            raise HTTPException(status_code=400, detail="Некорректный размер или SHA-256 файла в manifest")
        if archive_name in record_map:
            raise HTTPException(status_code=400, detail="Manifest содержит повторяющиеся файлы")
        record_map[archive_name] = (relative, size, checksum.lower())

    if "data/" + database_relative.as_posix() not in record_map:
        raise HTTPException(400, "В архиве отсутствует заявленная база SQLite")

    archive_names = {
        item.filename for item in entries if item.filename != "manifest.json"
    }
    if archive_names != set(record_map):
        raise HTTPException(
            status_code=400,
            detail="Список файлов в ZIP не совпадает с manifest; резервная копия неполная или изменена",
        )

    staged_data.mkdir(parents=True, exist_ok=True)
    for item in entries:
        if item.filename == "manifest.json":
            continue
        relative, expected_size, expected_hash = record_map[item.filename]
        destination = (staged_data / relative).resolve()
        if staged_data.resolve() not in destination.parents:
            raise HTTPException(status_code=400, detail="Недопустимый путь внутри архива")
        destination.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        copied = 0
        with archive.open(item) as source, destination.open("wb") as target:
            while chunk := source.read(1024 * 1024):
                copied += len(chunk)
                if copied > expected_size:
                    raise HTTPException(status_code=400, detail="Размер файла не совпадает с manifest")
                digest.update(chunk)
                target.write(chunk)
        if copied != expected_size or digest.hexdigest() != expected_hash:
            raise HTTPException(
                status_code=400,
                detail=f"Проверка целостности не пройдена: {item.filename}",
            )

    staged_database = staged_data / database_relative
    # Старые экспорты могли сохранить пустой WAL и служебный SHM при чтении снимка.
    for suffix in ("-wal", "-shm", "-journal"):
        sidecar = Path(str(staged_database) + suffix)
        if sidecar.exists():
            if suffix != "-shm" and sidecar.stat().st_size:
                raise HTTPException(400, "База в архиве не является автономным снимком SQLite")
            sidecar.unlink()
    _validate_database(staged_database)
    _require_complete_media(staged_database, staged_data)
    if expected_database != database_relative:
        destination = staged_data / expected_database
        if destination.exists() or any(Path(str(destination) + suffix).exists() for suffix in ("-wal", "-shm", "-journal")):
            raise HTTPException(409, "Путь базы на новом сервере занят другим файлом из архива")
        destination.parent.mkdir(parents=True, exist_ok=True)
        staged_database.rename(destination)
    return 0


def _prepare_restore_archive(archive_path: Path, staged_data: Path) -> int:
    data_dir = DATA_DIR.resolve()
    expected_database = _database_relative_path(data_dir)
    try:
        with zipfile.ZipFile(archive_path) as archive:
            entries = _validate_archive_entries(archive)
            _require_backup_space(archive_path.parent, sum(item.file_size for item in entries))
            manifest = _read_archive_manifest(archive)
            if manifest.get("format") != FULL_BACKUP_FORMAT:
                raise HTTPException(status_code=400, detail="Формат резервной копии UknowApp не поддерживается")
            return _extract_v2_archive(archive, entries, manifest, staged_data, expected_database)
    except zipfile.BadZipFile as exc:
        raise HTTPException(status_code=400, detail="Файл не является корректным ZIP-архивом") from exc


def _write_restore_record(marker_path: Path, payload: dict) -> None:
    temporary = marker_path.with_name(marker_path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as target:
        json.dump(payload, target, ensure_ascii=False, separators=(",", ":"))
        target.flush()
        os.fsync(target.fileno())
    os.replace(temporary, marker_path)
    descriptor = os.open(marker_path.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _finish_restore(data_dir: Path, marker: dict, status: str) -> None:
    _write_restore_record(data_dir / RESTORE_RESULT_NAME, {
        "id": marker["stage"].removeprefix(RESTORE_STAGE_PREFIX),
        "status": status,
        "finished_at": datetime.now(UTC).isoformat(),
    })
    (data_dir / PENDING_RESTORE_NAME).unlink(missing_ok=True)


def _restore_status(data_dir: Path) -> dict | None:
    for name in (PENDING_RESTORE_NAME, RESTORE_RESULT_NAME):
        try:
            record = json.loads((data_dir / name).read_text(encoding="utf-8"))
        except FileNotFoundError:
            continue
        if name == PENDING_RESTORE_NAME:
            return {"id": record["stage"].removeprefix(RESTORE_STAGE_PREFIX), "status": "pending"}
        return record
    return None


def _control_names(stage_name: str, backup_name: str) -> set[str]:
    return {
        PENDING_RESTORE_NAME,
        PENDING_RESTORE_NAME + ".tmp",
        RESTORE_RESULT_NAME,
        stage_name,
        backup_name,
    }


def _rollback_partial_restore(
    data_dir: Path,
    stage_name: str,
    backup_name: str,
    original_entries: list[str],
) -> None:
    backup_dir = data_dir / backup_name
    protected = _control_names(stage_name, backup_name)
    for child in list(data_dir.iterdir()):
        if child.name in protected:
            continue
        if child.name in original_entries and not (backup_dir / child.name).exists():
            continue
        _remove_path(child)
    if backup_dir.exists():
        for previous in list(backup_dir.iterdir()):
            destination = data_dir / previous.name
            if destination.exists() or destination.is_symlink():
                _remove_path(destination)
            previous.rename(destination)
        # Сохраняем папку копии до фиксации восстановления.


def _cleanup_orphaned_restore_stages(data_dir: Path) -> None:
    for child in data_dir.iterdir():
        if child.name.startswith(RESTORE_STAGE_PREFIX) and child.is_dir():
            shutil.rmtree(child, ignore_errors=True)
    (data_dir / RESTORE_UPLOAD_LOCK).unlink(missing_ok=True)


def _database_files():
    database = _database_path()
    return [Path(str(database) + suffix) for suffix in ("", "-wal", "-shm", "-journal")]


def _rollback_restore(data_dir, marker):
    engine.dispose()
    backup = data_dir / marker["backup"]
    if marker.get("kind") == "database":
        for path in _database_files():
            saved = backup / path.name
            if saved.exists():
                saved.replace(path)
            elif path.name not in marker["original_entries"]:
                path.unlink(missing_ok=True)
    else:
        _rollback_partial_restore(data_dir, marker["stage"], marker["backup"], marker["original_entries"])


def finish_startup_restore(success: bool) -> None:
    root = DATA_DIR.resolve()
    record = root / PENDING_RESTORE_NAME
    marker = json.loads(record.read_text(encoding="utf-8"))
    if marker["status"] != "verifying":
        raise RuntimeError("Восстановление не ожидает проверки запуска")
    if not success:
        _rollback_restore(root, marker)
    marker["status"] = "committed" if success else "rolled_back"
    _write_restore_record(record, marker)
    _finish_restore_cleanup(root, marker)


def _finish_restore_cleanup(root: Path, marker: dict) -> None:
    for name in ("backup", "stage"):
        directory = root / marker[name]
        if directory.exists():
            shutil.rmtree(directory)
    _finish_restore(root, marker, "completed" if marker["status"] == "committed" else "failed")


def apply_pending_data_restore() -> bool:
    """Восстановить данные до миграций и фоновых задач."""
    data_dir = DATA_DIR.resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    marker_path = data_dir / PENDING_RESTORE_NAME
    (data_dir / RESTORE_UPLOAD_LOCK).unlink(missing_ok=True)
    if not marker_path.is_file():
        _cleanup_orphaned_restore_stages(data_dir)
        return False

    try:
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
        stage_name = marker.get("stage")
        backup_name = marker.get("backup")
        if (
            not isinstance(stage_name, str)
            or not stage_name.startswith(RESTORE_STAGE_PREFIX)
            or Path(stage_name).name != stage_name
            or not isinstance(backup_name, str)
            or not backup_name.startswith(RESTORE_BACKUP_PREFIX)
            or Path(backup_name).name != backup_name
        ):
            raise RuntimeError("Некорректный указатель на подготовленную резервную копию")

        stage_dir = data_dir / stage_name
        backup_dir = data_dir / backup_name
        archive_path = stage_dir / "backup.zip"
        staged_data = stage_dir / "data"
        status = marker.get("status")

        if status in {"committed", "rolled_back"}:
            _finish_restore_cleanup(data_dir, marker)
            return False

        if status in {"applying", "verifying"}:
            if not backup_dir.is_dir() or backup_dir.is_symlink():
                raise RuntimeError("Не найдена страховочная копия незавершённого восстановления")
            original_entries = marker.get("original_entries")
            if not isinstance(original_entries, list) or not all(
                isinstance(name, str) and Path(name).name == name for name in original_entries
            ):
                raise RuntimeError("Невозможно безопасно откатить незавершённое восстановление")
            _rollback_restore(data_dir, marker)
            _finish_restore(data_dir, marker, "failed")
            shutil.rmtree(backup_dir, ignore_errors=True)
            shutil.rmtree(stage_dir, ignore_errors=True)
            return False
        elif status != "prepared":
            raise RuntimeError("Неизвестное состояние восстановления резервной копии")

        if backup_dir.exists():
            shutil.rmtree(backup_dir)
        if staged_data.exists():
            shutil.rmtree(staged_data)
        try:
            database_only = marker.get("kind") == "database"
            if database_only:
                uploaded = stage_dir / "database.sqlite3"
                if marker.get("sha256") != _hash_file(uploaded)[1]:
                    raise ValueError("Контрольная сумма SQLite не совпадает")
                _validate_database(uploaded)
                _require_complete_media(uploaded, data_dir)
            else:
                _prepare_restore_archive(archive_path, staged_data)
        except Exception:
            logger.exception(
                "Подготовленный архив не прошёл повторную проверку; текущие данные не изменены",
            )
            shutil.rmtree(stage_dir, ignore_errors=True)
            _finish_restore(data_dir, marker, "failed")
            return False
        engine.dispose()
        if database_only:
            originals = [path for path in _database_files() if path.exists()]
        else:
            protected = _control_names(stage_name, backup_name)
            originals = [child for child in data_dir.iterdir() if child.name not in protected]
        original_entries = [child.name for child in originals]
        backup_dir.mkdir()
        marker["status"] = "applying"
        marker["original_entries"] = original_entries
        _write_restore_record(marker_path, marker)

        try:
            for child in originals:
                child.rename(backup_dir / child.name)
            if database_only:
                uploaded.rename(_database_path())
            else:
                for child in staged_data.iterdir():
                    child.rename(data_dir / child.name)
            _validate_database(_database_path())
            marker["status"] = "verifying"
            _write_restore_record(marker_path, marker)
        except Exception:
            try:
                _rollback_restore(data_dir, marker)
            except Exception as rollback_error:
                logger.exception("Полный откат восстановления UknowApp не удался")
                raise RuntimeError(
                    "Восстановление завершилось ошибкой, автоматический откат также не удался",
                ) from rollback_error
            shutil.rmtree(stage_dir, ignore_errors=True)
            _finish_restore(data_dir, marker, "failed")
            shutil.rmtree(backup_dir, ignore_errors=True)
            engine.dispose()
            logger.exception("Резервная копия UknowApp не применена; исходные данные восстановлены")
            return False

        return True
    except Exception:
        logger.exception("Не удалось применить подготовленную резервную копию UknowApp")
        raise


def _automatic_restart_enabled() -> bool:
    return os.getenv("UKNOWAPP_AUTO_RESTART_ON_RESTORE", "").strip().lower() in {
        "1", "true", "yes", "on",
    }


def _restart_backend_after_response() -> None:
    if _automatic_restart_enabled():
        os.kill(os.getpid(), signal.SIGTERM)


def _add_media_files(archive: zipfile.ZipFile) -> int:
    count = 0
    if not MEDIA_DIR.exists():
        return count
    media_root = MEDIA_DIR.resolve()
    for path in MEDIA_DIR.rglob("*"):
        if not path.is_file():
            continue
        resolved = path.resolve()
        if media_root not in resolved.parents:
            continue
        archive.write(resolved, "media/" + resolved.relative_to(media_root).as_posix())
        count += 1
    return count


@router.get("/restore-status")
def restore_status(_: Admin):
    return {"restore": _restore_status(DATA_DIR)}


@router.get("/stats")
def data_stats(_: Admin):
    database_engine, database_size = database_storage_info()

    with SessionLocal() as db:
        users = db.query(User).all()
        assignments = db.query(Assignment).all()
        media_counts = {"images": 0, "audio": 0, "videos": 0, "other": 0}
        for row in db.query(Message.metadata_json).all():
            try:
                # Older backups can contain legacy JSON metadata: null, arrays,
                # strings and malformed media objects are not fatal to stats.
                metadata = json.loads(row[0] or "{}")
                if not isinstance(metadata, dict):
                    continue
                media = metadata.get("media")
                if not isinstance(media, dict):
                    continue
                relative = media.get("local_path")
                if not relative:
                    continue
                path = (MEDIA_DIR / _safe_relative(relative)).resolve()
                if MEDIA_DIR.resolve() not in path.parents or not path.is_file():
                    continue
                mime_value = media.get("mime_type")
                kind_value = media.get("kind")
                mime = mime_value.lower() if isinstance(mime_value, str) else ""
                kind = kind_value.lower() if isinstance(kind_value, str) else ""
                if mime.startswith("image/") or kind in {"photo", "sticker"}:
                    media_counts["images"] += 1
                elif mime.startswith("audio/") or kind in {"audio", "voice"}:
                    media_counts["audio"] += 1
                elif mime.startswith("video/") or kind in {
                    "video", "video_note", "animation", "video_sticker",
                }:
                    media_counts["videos"] += 1
                else:
                    media_counts["other"] += 1
            except (TypeError, ValueError, OSError, HTTPException):
                continue

        message_count = db.query(Message).count()
        personal_message_count = db.query(PersonalMessage).count()
        active_assignments = sum(1 for item in assignments if item.active)
        return {
            "restore": _restore_status(DATA_DIR),
            "database_bytes": database_size,
            "database_engine": database_engine,
            "database_backups_supported": database_engine == "sqlite",
            "media_bytes": _folder_size(MEDIA_DIR),
            "users": len(users),
            "teachers": sum(1 for item in users if item.role == "teacher"),
            "students": sum(1 for item in users if item.role == "student"),
            "assignments": len(assignments),
            "active_assignments": active_assignments,
            "closed_assignments": len(assignments) - active_assignments,
            "conversations": db.query(Conversation).count(),
            "personal_conversations": db.query(PersonalConversation).count(),
            "messages": message_count,
            "personal_messages": personal_message_count,
            "total_messages": message_count + personal_message_count,
            "telegram_groups": db.query(StudentTelegramGroup).count(),
            "teacher_panels": db.query(TeacherPanel).count(),
            "teacher_sessions": db.query(TeacherSession).count(),
            "panel_sessions": db.query(PanelSession).count(),
            "connection_codes": db.query(func.count(func.distinct(ConnectionCode.user_id))).join(
                User, ConnectionCode.user_id == User.id,
            ).filter(
                User.role.in_(("teacher", "student")),
                User.web_password_hash.is_not(None),
                ConnectionCode.used_at.is_(None),
                ConnectionCode.expires_at > datetime.now(UTC) + timedelta(days=365),
            ).scalar(),
            "media_files": sum(media_counts.values()),
            **{f"media_{key}": value for key, value in media_counts.items()},
        }


@router.get("/database")
def download_database(_: Admin):
    database = _database_path()
    if not database.is_file():
        raise HTTPException(status_code=404, detail="Файл базы данных не найден")
    backup_path = _temporary_path(".uknowapp-db-", ".sqlite3", DATA_DIR)
    try:
        _create_database_snapshot(backup_path)
        return FileResponse(
            backup_path,
            media_type="application/vnd.sqlite3",
            filename="uknowapp-backup.sqlite3",
            background=BackgroundTask(_remove_temp, str(backup_path)),
        )
    except Exception:
        backup_path.unlink(missing_ok=True)
        raise


@router.get("/full")
def download_full_backup(_: Admin):
    _database_path()  # ZIP contains SQLite; PostgreSQL requires pg_dump.
    data_dir = DATA_DIR.resolve()
    if (data_dir / PENDING_RESTORE_NAME).exists():
        raise HTTPException(
            status_code=409,
            detail="Уже подготовлено восстановление. Перезапустите backend для его применения.",
        )
    staging_root = Path(tempfile.mkdtemp(prefix=".uknowapp-backup-", dir=data_dir))
    archive_path = staging_root / "uknowapp-full-backup.zip"
    try:
        _build_full_backup(archive_path, staging_root)
        return FileResponse(
            archive_path,
            media_type="application/zip",
            filename="uknowapp-full-backup.zip",
            background=BackgroundTask(shutil.rmtree, str(staging_root), ignore_errors=True),
        )
    except Exception:
        shutil.rmtree(staging_root, ignore_errors=True)
        raise


@router.get("/media")
def download_media_archive(_: Admin):
    archive_path = _temporary_path(".uknowapp-media-", ".zip", DATA_DIR)
    try:
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps({
                "format": "uknowapp-media-v1",
                "created_at": datetime.now(UTC).isoformat(),
            }, ensure_ascii=False))
            _add_media_files(archive)
        return FileResponse(
            archive_path,
            media_type="application/zip",
            filename="uknowapp-media.zip",
            background=BackgroundTask(_remove_temp, str(archive_path)),
        )
    except Exception:
        archive_path.unlink(missing_ok=True)
        raise


@router.post("/full")
async def restore_full_backup(_: Admin, file: Annotated[UploadFile, File()]):
    _database_path()  # Never apply an SQLite archive to PostgreSQL.
    if not (file.filename or "").lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="Загрузите ZIP-файл полной резервной копии")

    return await _stage_upload(file, "full")


async def _stage_upload(file: UploadFile, kind: str):
    _database_path()
    data_dir = DATA_DIR.resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    marker_path = data_dir / PENDING_RESTORE_NAME
    lock_path = data_dir / RESTORE_UPLOAD_LOCK
    if marker_path.exists():
        raise HTTPException(
            status_code=409,
            detail="Восстановление уже подготовлено. Перезапустите backend для его применения.",
        )
    try:
        lock_descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail="Другая резервная копия уже загружается") from exc

    stage_dir = None
    marker_created = False
    try:
        os.close(lock_descriptor)
        stage_dir = Path(tempfile.mkdtemp(prefix=RESTORE_STAGE_PREFIX, dir=data_dir))
        if marker_path.exists():
            raise HTTPException(409, "Восстановление уже подготовлено")
        archive_path = stage_dir / ("backup.zip" if kind == "full" else "database.sqlite3")
        with archive_path.open("wb") as target:
            while chunk := await file.read(1024 * 1024):
                _require_backup_space(Path(target.name).parent, len(chunk))
                target.write(chunk)

        checksum = None
        if kind == "database":
            _database_relative_path(data_dir)
            _validate_database(archive_path)
            _require_complete_media(archive_path, data_dir)
            checksum = _hash_file(archive_path)[1]
        else:
            _prepare_restore_archive(archive_path, stage_dir / "data")
            shutil.rmtree(stage_dir / "data")
        backup_name = RESTORE_BACKUP_PREFIX + uuid.uuid4().hex
        _write_restore_record(marker_path, {
            "status": "prepared",
            "kind": kind,
            "sha256": checksum,
            "created_at": datetime.now(UTC).isoformat(),
            "stage": stage_dir.name,
            "backup": backup_name,
            "missing_media_references": 0,
        })
        marker_created = True

        automatic_restart = _automatic_restart_enabled()
        message = (
            "Архив проверен. Backend будет перезапущен и применит все данные до запуска Telegram."
            if automatic_restart
            else (
                "Архив проверен и подготовлен. Перезапустите backend: при следующем запуске "
                "данные будут заменены до запуска Telegram."
            )
        )
        return JSONResponse(
            status_code=202,
            content={
                "ok": True,
                "restore_id": stage_dir.name.removeprefix(RESTORE_STAGE_PREFIX),
                "restart_required": True,
                "automatic_restart": automatic_restart,
                "warnings": [],
                "message": message,
            },
            background=BackgroundTask(_restart_backend_after_response) if automatic_restart else None,
        )
    except Exception:
        if stage_dir and not marker_created:
            shutil.rmtree(stage_dir, ignore_errors=True)
        raise
    finally:
        lock_path.unlink(missing_ok=True)
        await file.close()


@router.post("/database")
async def restore_database(_: Admin, file: Annotated[UploadFile, File()]):
    _database_path()
    if not (file.filename or "").lower().endswith((".db", ".sqlite", ".sqlite3")):
        raise HTTPException(status_code=400, detail="Загрузите файл SQLite (.db, .sqlite или .sqlite3)")
    return await _stage_upload(file, "database")


@router.delete("/dialogues")
def cleanup_dialogues(days: int, _: Admin, db: Annotated[Session, Depends(_get_db)]):
    if days not in {30, 60, 180, 360}:
        raise HTTPException(status_code=400, detail="Выберите срок 30, 60, 180 или 360 дней")
    cutoff = datetime.now(UTC) - timedelta(days=days)
    old_rows = db.scalars(select(Message).where(Message.created_at < cutoff)).all()
    old_personal_rows = db.scalars(
        select(PersonalMessage).where(PersonalMessage.created_at < cutoff),
    ).all()
    deleted_messages = len(old_rows)
    deleted_personal = len(old_personal_rows)
    changed_conversation_ids = {row.conversation_id for row in old_rows}
    changed_personal_ids = {row.conversation_id for row in old_personal_rows}
    db.query(PersonalMessage).filter(
        PersonalMessage.created_at < cutoff,
    ).delete(synchronize_session=False)
    db.query(Message).filter(
        Message.created_at < cutoff,
    ).delete(synchronize_session=False)
    db.commit()
    if changed_conversation_ids or changed_personal_ids:
        publish_chat_update(0)
    deleted_files = 0
    media_root = MEDIA_DIR.resolve()
    for row in old_rows:
        relative = (json.loads(row.metadata_json or "{}").get("media") or {}).get("local_path")
        if relative:
            target = (media_root / _safe_relative(relative)).resolve()
            if media_root in target.parents and target.is_file():
                deleted_files += 1
        delete_message_media(row.metadata_json)
    if MEDIA_DIR.exists():
        for path in sorted(MEDIA_DIR.rglob("*"), reverse=True):
            if path.is_dir():
                with contextlib.suppress(OSError):
                    path.rmdir()
    return {
        "ok": True,
        "days": days,
        "deleted_messages": deleted_messages,
        "deleted_personal_messages": deleted_personal,
        "deleted_media_files": deleted_files,
    }
