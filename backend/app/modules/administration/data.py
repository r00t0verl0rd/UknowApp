"""Администрирование данных, резервное копирование и перенос всего каталога data."""

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
from app.core.security import require_admin
from app.event_hub import publish_chat_update
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

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin/data", tags=["admin-data"])
Admin = Annotated[str, Depends(require_admin)]


def _get_db():
    with SessionLocal() as db:
        yield db

DATA_DIR = MEDIA_DIR.parent.resolve()
PENDING_RESTORE_NAME = ".uknowapp-restore-pending.json"
RESTORE_STAGE_PREFIX = ".uknowapp-restore-stage-"
RESTORE_BACKUP_PREFIX = ".uknowapp-restore-backup-"
RESTORE_UPLOAD_LOCK = ".uknowapp-restore-upload.lock"
INTERNAL_PREFIX = ".uknowapp-"

MAX_DATABASE_BYTES = 1024 * 1024 * 1024
MAX_ARCHIVE_BYTES = 2 * 1024 * 1024 * 1024
MAX_UNPACKED_ARCHIVE_BYTES = 4 * 1024 * 1024 * 1024
MAX_ARCHIVE_ENTRIES = 100000
FULL_BACKUP_FORMAT = "uknowapp-full-backup-v2"
LEGACY_FULL_BACKUP_FORMAT = "uknowapp-full-backup-v1"


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
    return Path(*relative.parts[1:])


def _create_database_snapshot(destination: Path) -> None:
    database = _database_path()
    if not database.is_file():
        raise HTTPException(status_code=404, detail="Файл базы данных не найден")
    with sqlite3.connect(database) as source, sqlite3.connect(destination) as target:
        source.backup(target)


def _iter_data_files(
    data_dir: Path,
    database: Path,
    *,
    excluded_top_level: set[str] | None = None,
):
    root = data_dir.resolve()
    database = database.resolve()
    excluded = excluded_top_level or set()
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
                if not name.startswith(INTERNAL_PREFIX) and name not in excluded
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


def _copy_live_files(
    destination: Path,
    *,
    excluded_top_level: set[str] | None = None,
) -> None:
    database = _database_path()
    for source, relative in _iter_data_files(
        DATA_DIR,
        database,
        excluded_top_level=excluded_top_level,
    ):
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


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
    with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as connection:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(messages)").fetchall()
        }
        if "metadata_json" not in columns:
            return 0
        for (raw_metadata,) in connection.execute("SELECT metadata_json FROM messages"):
            try:
                payload = json.loads(raw_metadata or "{}")
                media = payload.get("media") or {} if isinstance(payload, dict) else {}
                relative = media.get("local_path") if isinstance(media, dict) else None
                if not relative:
                    continue
                target = (media_root / _safe_relative(relative)).resolve()
                if media_root not in target.parents or not target.is_file():
                    missing += 1
            except (HTTPException, TypeError, ValueError, OSError):
                missing += 1
    return missing


def _validate_database(path: Path) -> None:
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as uploaded:
            integrity = uploaded.execute("PRAGMA integrity_check").fetchone()
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
        if relative == database_relative.as_posix() and size > MAX_DATABASE_BYTES:
            raise HTTPException(status_code=413, detail="База данных превышает 1 ГБ")
        if total_unpacked > MAX_UNPACKED_ARCHIVE_BYTES:
            raise HTTPException(status_code=413, detail="Каталог data превышает лимит архива 4 ГБ")
        file_records.append({
            "path": "data/" + relative,
            "size": size,
            "sha256": checksum,
        })

    missing_media = _count_missing_media_references(staged_database, staged_data)
    manifest = {
        "format": FULL_BACKUP_FORMAT,
        "format_version": 2,
        "app_version": "0.1.0",
        "created_at": datetime.now(UTC).isoformat(),
        "database_path": database_relative.as_posix(),
        "files": file_records,
        "file_count": len(file_records),
        "unpacked_bytes": total_unpacked,
        "missing_media_references": missing_media,
    }
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
            json.dumps(manifest, ensure_ascii=False, separators=(",", ":")),
        )
    if archive_path.stat().st_size > MAX_ARCHIVE_BYTES:
        raise HTTPException(status_code=413, detail="Резервная копия превышает 2 ГБ")
    return manifest


def _validate_archive_limits(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    entries = archive.infolist()
    if len(entries) > MAX_ARCHIVE_ENTRIES:
        raise HTTPException(status_code=413, detail="В архиве слишком много файлов")
    if sum(item.file_size for item in entries) > MAX_UNPACKED_ARCHIVE_BYTES:
        raise HTTPException(status_code=413, detail="Содержимое архива превышает 4 ГБ")
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
    if database_relative != expected_database:
        raise HTTPException(
            status_code=409,
            detail="Резервная копия использует другой путь к SQLite. Проверьте DATABASE_URL на новом сервере.",
        )

    records = manifest.get("files")
    if not isinstance(records, list) or not records or len(records) > MAX_ARCHIVE_ENTRIES:
        raise HTTPException(status_code=400, detail="В manifest отсутствует список файлов data")
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
        if relative == database_relative and size > MAX_DATABASE_BYTES:
            raise HTTPException(status_code=413, detail="База данных в архиве превышает 1 ГБ")
        record_map[archive_name] = (relative, size, checksum.lower())

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
    _validate_database(staged_database)
    return _count_missing_media_references(staged_database, staged_data)


def _extract_legacy_archive(
    archive: zipfile.ZipFile,
    entries: list[zipfile.ZipInfo],
    manifest: dict,
    staged_data: Path,
    expected_database: Path,
) -> int:
    if manifest.get("format") != LEGACY_FULL_BACKUP_FORMAT:
        raise HTTPException(status_code=400, detail="Формат резервной копии не поддерживается")
    allowed_names = {"manifest.json", "database.sqlite3"}
    for item in entries:
        if item.filename in allowed_names:
            continue
        if not item.filename.startswith("media/"):
            raise HTTPException(status_code=400, detail="Старая резервная копия содержит неизвестные файлы")
        _safe_relative(item.filename[6:])

    database_info = next((item for item in entries if item.filename == "database.sqlite3"), None)
    if database_info is None:
        raise HTTPException(status_code=400, detail="В старой резервной копии отсутствует база данных")
    if database_info.file_size > MAX_DATABASE_BYTES:
        raise HTTPException(status_code=413, detail="База данных в архиве превышает 1 ГБ")

    staged_data.mkdir(parents=True, exist_ok=True)
    _copy_live_files(staged_data, excluded_top_level={"media"})
    database_destination = staged_data / expected_database
    database_destination.parent.mkdir(parents=True, exist_ok=True)
    with archive.open(database_info) as source, database_destination.open("wb") as target:
        shutil.copyfileobj(source, target)

    media_root = staged_data / "media"
    for item in entries:
        if not item.filename.startswith("media/"):
            continue
        relative = _safe_relative(item.filename[6:])
        destination = (media_root / relative).resolve()
        if media_root.resolve() not in destination.parents:
            raise HTTPException(status_code=400, detail="Недопустимый путь к медиафайлу")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with archive.open(item) as source, destination.open("wb") as target:
            shutil.copyfileobj(source, target)

    _validate_database(database_destination)
    return _count_missing_media_references(database_destination, staged_data)


def _prepare_restore_archive(archive_path: Path, staged_data: Path) -> dict:
    data_dir = DATA_DIR.resolve()
    expected_database = _database_relative_path(data_dir)
    try:
        with zipfile.ZipFile(archive_path) as archive:
            entries = _validate_archive_limits(archive)
            manifest = _read_archive_manifest(archive)
            archive_format = manifest.get("format")
            if archive_format == FULL_BACKUP_FORMAT:
                missing_media = _extract_v2_archive(
                    archive, entries, manifest, staged_data, expected_database,
                )
                return {"legacy": False, "missing_media": missing_media}
            if archive_format == LEGACY_FULL_BACKUP_FORMAT:
                missing_media = _extract_legacy_archive(
                    archive, entries, manifest, staged_data, expected_database,
                )
                return {"legacy": True, "missing_media": missing_media}
            raise HTTPException(status_code=400, detail="Формат резервной копии UknowApp не поддерживается")
    except zipfile.BadZipFile as exc:
        raise HTTPException(status_code=400, detail="Файл не является корректным ZIP-архивом") from exc


def _write_pending_marker(marker_path: Path, payload: dict) -> None:
    temporary = marker_path.with_name(marker_path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as target:
        json.dump(payload, target, ensure_ascii=False, separators=(",", ":"))
        target.flush()
        os.fsync(target.fileno())
    os.replace(temporary, marker_path)


def _control_names(stage_name: str, backup_name: str) -> set[str]:
    return {
        PENDING_RESTORE_NAME,
        PENDING_RESTORE_NAME + ".tmp",
        stage_name,
        backup_name,
    }


def _rollback_partial_restore(
    data_dir: Path,
    stage_name: str,
    backup_name: str,
    original_entries: list[str],
) -> None:
    stage_dir = data_dir / stage_name
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
        backup_dir.rmdir()


def _cleanup_orphaned_restore_stages(data_dir: Path) -> None:
    for child in data_dir.iterdir():
        if child.name.startswith(RESTORE_STAGE_PREFIX) and child.is_dir():
            shutil.rmtree(child, ignore_errors=True)
    (data_dir / RESTORE_UPLOAD_LOCK).unlink(missing_ok=True)


def apply_pending_data_restore() -> bool:
    """Apply a verified restore before DB migrations and background workers start."""
    data_dir = DATA_DIR.resolve()
    marker_path = data_dir / PENDING_RESTORE_NAME
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

        if status == "committed":
            shutil.rmtree(backup_dir, ignore_errors=True)
            shutil.rmtree(stage_dir, ignore_errors=True)
            marker_path.unlink(missing_ok=True)
            return True

        if status == "applying":
            original_entries = marker.get("original_entries")
            if not isinstance(original_entries, list) or not all(
                isinstance(name, str) and Path(name).name == name for name in original_entries
            ):
                raise RuntimeError("Невозможно безопасно откатить незавершённое восстановление")
            _rollback_partial_restore(data_dir, stage_name, backup_name, original_entries)
            marker["status"] = "prepared"
            marker.pop("original_entries", None)
            _write_pending_marker(marker_path, marker)
        elif status != "prepared":
            raise RuntimeError("Неизвестное состояние восстановления резервной копии")

        if backup_dir.exists():
            shutil.rmtree(backup_dir)
        if staged_data.exists():
            shutil.rmtree(staged_data)
        restore_info = _prepare_restore_archive(archive_path, staged_data)
        original_entries = [
            child.name for child in data_dir.iterdir()
            if child.name not in _control_names(stage_name, backup_name)
        ]
        backup_dir.mkdir()
        marker["status"] = "applying"
        marker["original_entries"] = original_entries
        _write_pending_marker(marker_path, marker)
        engine.dispose()

        try:
            for child in list(data_dir.iterdir()):
                if child.name in _control_names(stage_name, backup_name):
                    continue
                child.rename(backup_dir / child.name)
            for child in list(staged_data.iterdir()):
                child.rename(data_dir / child.name)

            _validate_database(_database_path())
            marker["status"] = "committed"
            marker["missing_media_references"] = restore_info["missing_media"]
            _write_pending_marker(marker_path, marker)
        except Exception:
            try:
                _rollback_partial_restore(data_dir, stage_name, backup_name, original_entries)
            except Exception as rollback_error:
                logger.exception("Полный откат восстановления UknowApp не удался")
                raise RuntimeError(
                    "Восстановление завершилось ошибкой, автоматический откат также не удался",
                ) from rollback_error
            shutil.rmtree(stage_dir, ignore_errors=True)
            marker_path.unlink(missing_ok=True)
            engine.dispose()
            logger.exception("Резервная копия UknowApp не применена; исходные данные восстановлены")
            return False

        shutil.rmtree(backup_dir, ignore_errors=True)
        shutil.rmtree(stage_dir, ignore_errors=True)
        marker_path.unlink(missing_ok=True)
        logger.info("Полная резервная копия UknowApp восстановлена до запуска приложения")
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


@router.get("/stats")
def data_stats(_: Admin):
    database = _database_path()
    backup_path = _temporary_path(".uknowapp-db-stats-", ".sqlite3", DATA_DIR)
    try:
        with sqlite3.connect(database) as source, sqlite3.connect(backup_path) as target:
            source.backup(target)
        database_size = backup_path.stat().st_size
    finally:
        backup_path.unlink(missing_ok=True)

    with SessionLocal() as db:
        users = db.query(User).all()
        assignments = db.query(Assignment).all()
        media_counts = {"images": 0, "audio": 0, "videos": 0, "other": 0}
        for row in db.query(Message.metadata_json).all():
            try:
                media = (json.loads(row[0] or "{}").get("media") or {})
                relative = media.get("local_path")
                if not relative:
                    continue
                path = (MEDIA_DIR / _safe_relative(relative)).resolve()
                if MEDIA_DIR.resolve() not in path.parents or not path.is_file():
                    continue
                mime = (media.get("mime_type") or "").lower()
                kind = (media.get("kind") or "").lower()
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
            "database_bytes": database_size,
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
    if not (file.filename or "").lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="Загрузите ZIP-файл полной резервной копии")

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
        archive_path = stage_dir / "backup.zip"
        total = 0
        with archive_path.open("wb") as target:
            while chunk := await file.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_ARCHIVE_BYTES:
                    raise HTTPException(status_code=413, detail="Архив превышает 2 ГБ")
                target.write(chunk)

        restore_info = _prepare_restore_archive(archive_path, stage_dir / "data")
        backup_name = RESTORE_BACKUP_PREFIX + uuid.uuid4().hex
        _write_pending_marker(marker_path, {
            "status": "prepared",
            "created_at": datetime.now(UTC).isoformat(),
            "stage": stage_dir.name,
            "backup": backup_name,
            "legacy_format": restore_info["legacy"],
            "missing_media_references": restore_info["missing_media"],
        })
        marker_created = True

        automatic_restart = _automatic_restart_enabled()
        warnings = []
        if restore_info["legacy"]:
            warnings.append(
                "Используется резервная копия старого формата: ключ Web Push и прочие файлы data "
                "в неё не входили; текущие файлы сервера сохранены.",
            )
        if restore_info["missing_media"]:
            warnings.append(
                f"В базе обнаружено ссылок на отсутствующие медиафайлы: {restore_info['missing_media']}.",
            )
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
                "restart_required": True,
                "automatic_restart": automatic_restart,
                "legacy_format": restore_info["legacy"],
                "warnings": warnings,
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
    if not (file.filename or "").lower().endswith((".db", ".sqlite", ".sqlite3")):
        raise HTTPException(status_code=400, detail="Загрузите файл SQLite (.db, .sqlite или .sqlite3)")
    database = _database_path()
    temp_path = _temporary_path(".uknowapp-restore-", ".sqlite3", DATA_DIR)
    total = 0
    try:
        with temp_path.open("wb") as handle:
            while chunk := await file.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_DATABASE_BYTES:
                    raise HTTPException(status_code=413, detail="Файл базы данных превышает 1 ГБ")
                handle.write(chunk)
        _validate_database(temp_path)
        database.parent.mkdir(parents=True, exist_ok=True)
        engine.dispose()
        with sqlite3.connect(temp_path) as source, sqlite3.connect(database) as target:
            source.backup(target)
            target.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        return {"ok": True, "message": "База данных восстановлена. Перезапустите панель."}
    finally:
        temp_path.unlink(missing_ok=True)
        await file.close()


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
                try:
                    path.rmdir()
                except OSError:
                    pass
    return {
        "ok": True,
        "days": days,
        "deleted_messages": deleted_messages,
        "deleted_personal_messages": deleted_personal,
        "deleted_media_files": deleted_files,
    }
