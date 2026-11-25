"""Administration: backup."""

import json
import os
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask
from . import common
from .common import Admin

router = APIRouter()


def _create_database_snapshot(destination: Path) -> None:
    database = common.database_path()
    if not database.is_file():
        raise HTTPException(status_code=404, detail="Файл базы данных не найден")
    common.require_backup_space(destination.parent, database.stat().st_size)
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
                if not name.startswith(common.INTERNAL_PREFIX) and name != "runtime"
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
            if name.startswith(common.INTERNAL_PREFIX):
                continue
            if source.is_symlink():
                raise HTTPException(
                    status_code=400,
                    detail="В каталоге data обнаружена символическая ссылка; перенесите её содержимое в обычный файл или каталог",
                )
            if not source.is_file() or source.resolve() == database or source.resolve() in sidecars:
                continue
            yield source, source.relative_to(root)


def _build_full_backup(archive_path: Path, staging_root: Path) -> dict:
    data_dir = common.DATA_DIR.resolve()
    database = common.database_path()
    database_relative = common.database_relative_path(data_dir)
    if not data_dir.is_dir():
        raise HTTPException(status_code=404, detail="Каталог data не найден")

    staged_data = staging_root / "data"
    staged_data.mkdir(parents=True)
    for source, relative in _iter_data_files(data_dir, database):
        target = staged_data / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        common.require_backup_space(target.parent, source.stat().st_size)
        shutil.copy2(source, target)

    # Snapshot SQLite using its backup API; never copy a live WAL as ordinary files.
    runtime_path = data_dir / "runtime" / "runtime.db"
    if runtime_path.is_file():
        destination = staged_data / "runtime" / "runtime.db"
        destination.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(runtime_path.as_uri() + "?mode=ro", uri=True) as source, sqlite3.connect(destination) as target:
            source.backup(target)

    staged_database = staged_data / database_relative
    staged_database.parent.mkdir(parents=True, exist_ok=True)
    _create_database_snapshot(staged_database)
    common.validate_database(staged_database)

    file_records = []
    total_unpacked = 0
    staged_files = sorted(path for path in staged_data.rglob("*") if path.is_file())
    if len(staged_files) > common.MAX_ARCHIVE_ENTRIES:
        raise HTTPException(status_code=413, detail="В каталоге data слишком много файлов")
    for path in staged_files:
        relative = path.relative_to(staged_data).as_posix()
        size, checksum = common.hash_file(path)
        total_unpacked += size
        file_records.append({
            "path": "data/" + relative,
            "size": size,
            "sha256": checksum,
        })

    common.require_complete_media(staged_database, staged_data)
    manifest = {
        "format": common.FULL_BACKUP_FORMAT,
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
    common.require_backup_space(archive_path.parent, total_unpacked + len(manifest_json))
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


def _add_media_files(archive: zipfile.ZipFile) -> int:
    count = 0
    if not common.MEDIA_DIR.exists():
        return count
    media_root = common.MEDIA_DIR.resolve()
    for path in common.MEDIA_DIR.rglob("*"):
        if not path.is_file():
            continue
        resolved = path.resolve()
        if media_root not in resolved.parents:
            continue
        archive.write(resolved, "media/" + resolved.relative_to(media_root).as_posix())
        count += 1
    return count


@router.get("/database")
def download_database(_: Admin):
    database = common.database_path()
    if not database.is_file():
        raise HTTPException(status_code=404, detail="Файл базы данных не найден")
    backup_path = common.temporary_path(".uknowapp-db-", ".sqlite3", common.DATA_DIR)
    try:
        _create_database_snapshot(backup_path)
        return FileResponse(
            backup_path,
            media_type="application/vnd.sqlite3",
            filename="uknowapp-backup.sqlite3",
            background=BackgroundTask(common.remove_temp, str(backup_path)),
        )
    except Exception:
        backup_path.unlink(missing_ok=True)
        raise


@router.get("/full")
def download_full_backup(_: Admin):
    common.database_path()  # ZIP contains SQLite; PostgreSQL requires pg_dump.
    data_dir = common.DATA_DIR.resolve()
    if (data_dir / common.PENDING_RESTORE_NAME).exists():
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
    archive_path = common.temporary_path(".uknowapp-media-", ".zip", common.DATA_DIR)
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
            background=BackgroundTask(common.remove_temp, str(archive_path)),
        )
    except Exception:
        archive_path.unlink(missing_ok=True)
        raise
