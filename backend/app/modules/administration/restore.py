"""Administration: restore."""

import hashlib
import json
import logging
import os
import shutil
import signal
import stat
import tempfile
import uuid
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from starlette.background import BackgroundTask

from app.core import runtime_database
from app.core.database import engine

from . import common
from .common import Admin

logger = logging.getLogger(__name__)
router = APIRouter()


def _validate_archive_entries(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    entries = archive.infolist()
    if len(entries) > common.MAX_ARCHIVE_ENTRIES + 1:
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
    if manifest.get("format") != common.FULL_BACKUP_FORMAT or manifest.get("format_version") != 2:
        raise HTTPException(status_code=400, detail="Версия полной резервной копии не поддерживается")
    database_relative = common.safe_relative(manifest.get("database_path", ""))
    if any(part.startswith(common.INTERNAL_PREFIX) for part in database_relative.parts):
        raise HTTPException(400, "Недопустимый путь к базе данных в архиве")

    records = manifest.get("files")
    if not isinstance(records, list) or not records or len(records) > common.MAX_ARCHIVE_ENTRIES:
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
        relative = common.safe_data_entry(archive_name)
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
    common.validate_database(staged_database)
    common.require_complete_media(staged_database, staged_data)
    if expected_database != database_relative:
        destination = staged_data / expected_database
        if destination.exists() or any(Path(str(destination) + suffix).exists() for suffix in ("-wal", "-shm", "-journal")):
            raise HTTPException(409, "Путь базы на новом сервере занят другим файлом из архива")
        destination.parent.mkdir(parents=True, exist_ok=True)
        staged_database.rename(destination)
    return 0


def _prepare_restore_archive(archive_path: Path, staged_data: Path) -> int:
    data_dir = common.DATA_DIR.resolve()
    expected_database = common.database_relative_path(data_dir)
    try:
        with zipfile.ZipFile(archive_path) as archive:
            entries = _validate_archive_entries(archive)
            common.require_backup_space(archive_path.parent, sum(item.file_size for item in entries))
            manifest = _read_archive_manifest(archive)
            if manifest.get("format") != common.FULL_BACKUP_FORMAT:
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
    _write_restore_record(data_dir / common.RESTORE_RESULT_NAME, {
        "id": marker["stage"].removeprefix(common.RESTORE_STAGE_PREFIX),
        "status": status,
        "finished_at": datetime.now(UTC).isoformat(),
    })
    (data_dir / common.PENDING_RESTORE_NAME).unlink(missing_ok=True)


def restore_state(data_dir: Path) -> dict | None:
    for name in (common.PENDING_RESTORE_NAME, common.RESTORE_RESULT_NAME):
        try:
            record = json.loads((data_dir / name).read_text(encoding="utf-8"))
        except FileNotFoundError:
            continue
        if name == common.PENDING_RESTORE_NAME:
            return {"id": record["stage"].removeprefix(common.RESTORE_STAGE_PREFIX), "status": "pending"}
        return record
    return None


def _control_names(stage_name: str, backup_name: str) -> set[str]:
    return {
        common.PENDING_RESTORE_NAME,
        common.PENDING_RESTORE_NAME + ".tmp",
        common.RESTORE_RESULT_NAME,
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
        common.remove_path(child)
    if backup_dir.exists():
        for previous in list(backup_dir.iterdir()):
            destination = data_dir / previous.name
            if destination.exists() or destination.is_symlink():
                common.remove_path(destination)
            previous.rename(destination)
        # Сохраняем папку копии до фиксации восстановления.


def _cleanup_orphaned_restore_stages(data_dir: Path) -> None:
    for child in data_dir.iterdir():
        if child.name.startswith(common.RESTORE_STAGE_PREFIX) and child.is_dir():
            shutil.rmtree(child, ignore_errors=True)
    (data_dir / common.RESTORE_UPLOAD_LOCK).unlink(missing_ok=True)


def _database_files():
    database = common.database_path()
    return [Path(str(database) + suffix) for suffix in ("", "-wal", "-shm", "-journal")]


def _rollback_restore(data_dir, marker):
    engine.dispose()
    runtime_database.engine.dispose()
    backup = data_dir / marker["backup"]
    if marker.get("kind") == "database":
        for path in _database_files():
            saved = backup / path.name
            if saved.exists():
                saved.replace(path)
            elif path.name not in marker["original_entries"]:
                path.unlink(missing_ok=True)
        runtime_dir = data_dir / "runtime"
        saved_runtime = backup / "runtime"
        if saved_runtime.is_dir():
            shutil.rmtree(runtime_dir, ignore_errors=True)
            saved_runtime.rename(runtime_dir)
        elif "runtime" not in marker["original_entries"]:
            shutil.rmtree(runtime_dir, ignore_errors=True)
    else:
        _rollback_partial_restore(data_dir, marker["stage"], marker["backup"], marker["original_entries"])


def finish_startup_restore(success: bool) -> None:
    root = common.DATA_DIR.resolve()
    record = root / common.PENDING_RESTORE_NAME
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
    data_dir = common.DATA_DIR.resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    marker_path = data_dir / common.PENDING_RESTORE_NAME
    (data_dir / common.RESTORE_UPLOAD_LOCK).unlink(missing_ok=True)
    if not marker_path.is_file():
        _cleanup_orphaned_restore_stages(data_dir)
        return False

    try:
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
        stage_name = marker.get("stage")
        backup_name = marker.get("backup")
        if (
            not isinstance(stage_name, str)
            or not stage_name.startswith(common.RESTORE_STAGE_PREFIX)
            or Path(stage_name).name != stage_name
            or not isinstance(backup_name, str)
            or not backup_name.startswith(common.RESTORE_BACKUP_PREFIX)
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
                if marker.get("sha256") != common.hash_file(uploaded)[1]:
                    raise ValueError("Контрольная сумма SQLite не совпадает")
                common.validate_database(uploaded)
                common.require_complete_media(uploaded, data_dir)
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
        runtime_database.engine.dispose()
        if database_only:
            originals = [path for path in [*_database_files(), data_dir / "runtime"] if path.exists()]
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
                uploaded.rename(common.database_path())
            else:
                for child in staged_data.iterdir():
                    child.rename(data_dir / child.name)
            common.validate_database(common.database_path())
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


@router.get("/restore-status")
def restore_status(_: Admin):
    return {"restore": restore_state(common.DATA_DIR)}


@router.post("/full")
def restore_full_backup(_: Admin, file: Annotated[UploadFile, File()]):
    common.database_path()  # Never apply an SQLite archive to PostgreSQL.
    if not (file.filename or "").lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="Загрузите ZIP-файл полной резервной копии")

    return _stage_upload(file, "full")


def _stage_upload(file: UploadFile, kind: str):
    common.database_path()
    data_dir = common.DATA_DIR.resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    marker_path = data_dir / common.PENDING_RESTORE_NAME
    lock_path = data_dir / common.RESTORE_UPLOAD_LOCK
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
        stage_dir = Path(tempfile.mkdtemp(prefix=common.RESTORE_STAGE_PREFIX, dir=data_dir))
        if marker_path.exists():
            raise HTTPException(409, "Восстановление уже подготовлено")
        archive_path = stage_dir / ("backup.zip" if kind == "full" else "database.sqlite3")
        with archive_path.open("wb") as target:
            while chunk := file.file.read(1024 * 1024):
                common.require_backup_space(Path(target.name).parent, len(chunk))
                target.write(chunk)

        checksum = None
        if kind == "database":
            common.database_relative_path(data_dir)
            common.validate_database(archive_path)
            common.require_complete_media(archive_path, data_dir)
            checksum = common.hash_file(archive_path)[1]
        else:
            _prepare_restore_archive(archive_path, stage_dir / "data")
            shutil.rmtree(stage_dir / "data")
        backup_name = common.RESTORE_BACKUP_PREFIX + uuid.uuid4().hex
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
            "Архив проверен. Backend будет перезапущен и применит все данные до запуска коннекторов."
            if automatic_restart
            else (
                "Архив проверен и подготовлен. Перезапустите backend: при следующем запуске "
                "данные будут заменены до запуска коннекторов."
            )
        )
        return JSONResponse(
            status_code=202,
            content={
                "ok": True,
                "restore_id": stage_dir.name.removeprefix(common.RESTORE_STAGE_PREFIX),
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
        file.file.close()


@router.post("/database")
def restore_database(_: Admin, file: Annotated[UploadFile, File()]):
    common.database_path()
    if not (file.filename or "").lower().endswith((".db", ".sqlite", ".sqlite3")):
        raise HTTPException(status_code=400, detail="Загрузите файл SQLite (.db, .sqlite или .sqlite3)")
    return _stage_upload(file, "database")
