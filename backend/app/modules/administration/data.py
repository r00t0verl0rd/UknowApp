"""Администрирование резервных копий, архива переписок и очистки данных."""

import json
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
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

router = APIRouter(prefix="/admin/data", tags=["admin-data"])
Admin = Annotated[str, Depends(require_admin)]
MAX_DATABASE_BYTES = 1024 * 1024 * 1024
MAX_ARCHIVE_BYTES = 2 * 1024 * 1024 * 1024
MAX_UNPACKED_ARCHIVE_BYTES = 4 * 1024 * 1024 * 1024
ARCHIVE_FORMAT = "uknowapp-dialogues-v1"


def _get_db():
    with SessionLocal() as db:
        yield db


def _database_path() -> Path:
    if engine.dialect.name != "sqlite" or not engine.url.database:
        raise HTTPException(status_code=501, detail="Резервное копирование доступно для SQLite")
    return Path(engine.url.database).resolve()


def _remove_temp(path: str) -> None:
    Path(path).unlink(missing_ok=True)


def _folder_size(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def _safe_relative(value: str) -> Path:
    candidate = PurePosixPath(value)
    if candidate.is_absolute() or not candidate.parts or any(part in {"", ".", ".."} for part in candidate.parts):
        raise HTTPException(status_code=400, detail="Архив содержит недопустимый путь к медиафайлу")
    return Path(*candidate.parts)


def _parse_datetime(value: str | None):
    return datetime.fromisoformat(value) if value else None


def _message_data(row, fields: tuple[str, ...]) -> dict:
    return {
        field: getattr(row, field).isoformat() if isinstance(getattr(row, field), datetime) else getattr(row, field)
        for field in fields
    }


def _count_rows(model: type) -> int:
    with SessionLocal() as db:
        return db.query(model).count()


def _create_database_snapshot(destination: Path) -> None:
    database = _database_path()
    with sqlite3.connect(database) as source, sqlite3.connect(destination) as target:
        source.backup(target)


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


def _validate_database(path: Path) -> None:
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as uploaded:
            integrity = uploaded.execute("PRAGMA integrity_check").fetchone()
            tables = {row[0] for row in uploaded.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    except sqlite3.Error as exc:
        raise HTTPException(status_code=400, detail="Не удалось прочитать базу данных в резервной копии") from exc
    if not integrity or integrity[0] != "ok" or not {"users", "messages", "conversations"}.issubset(tables):
        raise HTTPException(status_code=400, detail="Архив не содержит корректную базу данных UknowApp")


@router.get("/stats")
def data_stats(_: Admin):
    database = _database_path()
    handle = tempfile.NamedTemporaryFile(
        prefix="uknowapp-db-stats-", suffix=".sqlite3",
        dir=database.parent, delete=False,
    )
    backup_path = Path(handle.name)
    handle.close()
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
                elif mime.startswith("video/") or kind in {"video", "video_note", "animation", "video_sticker"}:
                    media_counts["videos"] += 1
                else:
                    media_counts["other"] += 1
            except (TypeError, ValueError, OSError):
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
    handle = tempfile.NamedTemporaryFile(prefix="uknowapp-db-", suffix=".sqlite3", dir=database.parent, delete=False)
    backup_path = Path(handle.name)
    handle.close()
    try:
        with sqlite3.connect(database) as source, sqlite3.connect(backup_path) as target:
            source.backup(target)
        return FileResponse(
            backup_path, media_type="application/vnd.sqlite3",
            filename="uknowapp-backup.sqlite3",
            background=BackgroundTask(_remove_temp, str(backup_path)),
        )
    except Exception:
        backup_path.unlink(missing_ok=True)
        raise


@router.get("/full")
def download_full_backup(_: Admin):
    database = _database_path()
    handle = tempfile.NamedTemporaryFile(prefix="uknowapp-full-", suffix=".zip", dir=database.parent, delete=False)
    archive_path = Path(handle.name)
    handle.close()
    snapshot_path = archive_path.with_suffix(".sqlite3")
    try:
        _create_database_snapshot(snapshot_path)
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps({
                "format": "uknowapp-full-backup-v1",
                "created_at": datetime.now(UTC).isoformat(),
            }, ensure_ascii=False))
            archive.write(snapshot_path, "database.sqlite3")
            _add_media_files(archive)
        return FileResponse(
            archive_path, media_type="application/zip",
            filename="uknowapp-full-backup.zip",
            background=BackgroundTask(_remove_temp, str(archive_path)),
        )
    except Exception:
        archive_path.unlink(missing_ok=True)
        raise
    finally:
        snapshot_path.unlink(missing_ok=True)


@router.get("/media")
def download_media_archive(_: Admin):
    database = _database_path()
    handle = tempfile.NamedTemporaryFile(prefix="uknowapp-media-", suffix=".zip", dir=database.parent, delete=False)
    archive_path = Path(handle.name)
    handle.close()
    try:
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps({
                "format": "uknowapp-media-v1",
                "created_at": datetime.now(UTC).isoformat(),
            }, ensure_ascii=False))
            _add_media_files(archive)
        return FileResponse(
            archive_path, media_type="application/zip",
            filename="uknowapp-media.zip",
            background=BackgroundTask(_remove_temp, str(archive_path)),
        )
    except Exception:
        archive_path.unlink(missing_ok=True)
        raise


@router.post("/full")
async def restore_full_backup(_: Admin, file: UploadFile = File(...)):
    if not (file.filename or "").lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="Загрузите ZIP-файл полной резервной копии")
    data_dir = _database_path().parent
    handle = tempfile.NamedTemporaryFile(prefix="uknowapp-full-upload-", suffix=".zip", dir=data_dir, delete=False)
    upload_path = Path(handle.name)
    stage = Path(tempfile.mkdtemp(prefix="uknowapp-full-stage-", dir=data_dir))
    old_media = stage / "previous-media"
    try:
        total = 0
        with handle:
            while chunk := await file.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_ARCHIVE_BYTES:
                    raise HTTPException(status_code=413, detail="Архив превышает 2 ГБ")
                handle.write(chunk)
        database_copy = stage / "database.sqlite3"
        staged_media = stage / "media"
        staged_media.mkdir()
        try:
            with zipfile.ZipFile(upload_path) as archive:
                entries = archive.infolist()
                if len(entries) > 100000 or sum(item.file_size for item in entries) > MAX_UNPACKED_ARCHIVE_BYTES:
                    raise HTTPException(status_code=413, detail="Содержимое архива слишком велико")
                names = {item.filename for item in entries}
                if not {"manifest.json", "database.sqlite3"}.issubset(names):
                    raise HTTPException(status_code=400, detail="В архиве отсутствует база данных UknowApp")
                for item in entries:
                    parts = PurePosixPath(item.filename).parts
                    if PurePosixPath(item.filename).is_absolute() or ".." in parts:
                        raise HTTPException(status_code=400, detail="Архив содержит небезопасный путь")
                manifest = json.loads(archive.read("manifest.json"))
                if manifest.get("format") != "uknowapp-full-backup-v1":
                    raise HTTPException(status_code=400, detail="Формат полной резервной копии не поддерживается")
                database_info = archive.getinfo("database.sqlite3")
                if database_info.file_size > MAX_DATABASE_BYTES:
                    raise HTTPException(status_code=413, detail="База данных в архиве превышает 1 ГБ")
                with archive.open("database.sqlite3") as source, database_copy.open("wb") as target:
                    shutil.copyfileobj(source, target)
                for item in entries:
                    if item.filename.startswith("media/") and not item.is_dir():
                        relative = _safe_relative(item.filename[6:])
                        destination = (staged_media / relative).resolve()
                        if staged_media.resolve() not in destination.parents:
                            raise HTTPException(status_code=400, detail="Недопустимый путь к медиафайлу")
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        with archive.open(item) as source, destination.open("wb") as target:
                            shutil.copyfileobj(source, target)
            _validate_database(database_copy)
            database = _database_path()
            if MEDIA_DIR.exists():
                MEDIA_DIR.rename(old_media)
            try:
                if staged_media.exists():
                    MEDIA_DIR.parent.mkdir(parents=True, exist_ok=True)
                    staged_media.rename(MEDIA_DIR)
                engine.dispose()
                with sqlite3.connect(database_copy) as source, sqlite3.connect(database) as target:
                    source.backup(target)
                    target.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except Exception:
                if MEDIA_DIR.exists():
                    shutil.rmtree(MEDIA_DIR, ignore_errors=True)
                if old_media.exists():
                    old_media.rename(MEDIA_DIR)
                raise
            shutil.rmtree(old_media, ignore_errors=True)
            return {"ok": True, "message": "Полная резервная копия восстановлена. Перезагрузите панель."}
        except zipfile.BadZipFile as exc:
            raise HTTPException(status_code=400, detail="Файл не является корректным ZIP-архивом") from exc
    finally:
        upload_path.unlink(missing_ok=True)
        shutil.rmtree(stage, ignore_errors=True)
        await file.close()


@router.post("/database")
async def restore_database(_: Admin, file: UploadFile = File(...)):
    if not (file.filename or "").lower().endswith((".db", ".sqlite", ".sqlite3")):
        raise HTTPException(status_code=400, detail="Загрузите файл SQLite (.db, .sqlite или .sqlite3)")
    database = _database_path()
    handle = tempfile.NamedTemporaryFile(prefix="uknowapp-restore-", suffix=".sqlite3", dir=database.parent, delete=False)
    temp_path = Path(handle.name)
    total = 0
    try:
        with handle:
            while chunk := await file.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_DATABASE_BYTES:
                    raise HTTPException(status_code=413, detail="Файл базы данных превышает 1 ГБ")
                handle.write(chunk)
        with sqlite3.connect(f"file:{temp_path}?mode=ro", uri=True) as uploaded:
            integrity = uploaded.execute("PRAGMA integrity_check").fetchone()
            tables = {row[0] for row in uploaded.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not integrity or integrity[0] != "ok" or not {"users", "messages", "conversations"}.issubset(tables):
                raise HTTPException(status_code=400, detail="Файл не является корректной базой данных UknowApp")
        database.parent.mkdir(parents=True, exist_ok=True)
        engine.dispose()
        with sqlite3.connect(temp_path) as source, sqlite3.connect(database) as target:
            source.backup(target)
            target.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        return {"ok": True, "message": "База данных восстановлена. Обновите страницу панели."}
    finally:
        temp_path.unlink(missing_ok=True)
        await file.close()


@router.get("/dialogues")
def download_dialogues(_: Admin):
    with SessionLocal() as db:
        messages = db.scalars(select(Message).order_by(Message.id)).all()
        personal_messages = db.scalars(select(PersonalMessage).order_by(PersonalMessage.id)).all()
        payload = {
            "manifest.json": {"format": ARCHIVE_FORMAT, "created_at": datetime.now(UTC).isoformat()},
            "messages.json": [_message_data(row, (
                "id", "conversation_id", "sender_id", "sender_role", "content_type",
                "text", "metadata_json", "delivery_status", "source_message_id",
                "destination_message_id", "created_at",
            )) for row in messages],
            "personal_messages.json": [_message_data(row, (
                "id", "conversation_id", "sender_id", "sender_role", "text",
                "admin_read_at", "participant_read_at", "created_at",
            )) for row in personal_messages],
        }
        handle = tempfile.NamedTemporaryFile(prefix="uknowapp-dialogues-", suffix=".zip", dir=_database_path().parent, delete=False)
        archive_path = Path(handle.name)
        handle.close()
        try:
            with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for name, value in payload.items():
                    archive.writestr(name, json.dumps(value, ensure_ascii=False, separators=(",", ":")))
                archived_paths = set()
                for row in messages:
                    metadata = json.loads(row.metadata_json or "{}")
                    relative = (metadata.get("media") or {}).get("local_path")
                    if not relative or relative in archived_paths:
                        continue
                    relative_path = _safe_relative(relative)
                    source = (MEDIA_DIR / relative_path).resolve()
                    if MEDIA_DIR.resolve() not in source.parents or not source.is_file():
                        continue
                    archive.write(source, "media/" + relative_path.as_posix())
                    archived_paths.add(relative)
            return FileResponse(
                archive_path, media_type="application/zip",
                filename="uknowapp-dialogues.zip",
                background=BackgroundTask(_remove_temp, str(archive_path)),
            )
        except Exception:
            archive_path.unlink(missing_ok=True)
            raise


@router.post("/dialogues")
async def restore_dialogues(_: Admin, file: UploadFile = File(...), db: Session = Depends(_get_db)):
    if not (file.filename or "").lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="Загрузите ZIP-архив переписок")
    data_dir = _database_path().parent
    handle = tempfile.NamedTemporaryFile(prefix="uknowapp-dialogues-upload-", suffix=".zip", dir=data_dir, delete=False)
    temp_path = Path(handle.name)
    total = 0
    try:
        with handle:
            while chunk := await file.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_ARCHIVE_BYTES:
                    raise HTTPException(status_code=413, detail="Архив превышает 2 ГБ")
                handle.write(chunk)
        stage = Path(tempfile.mkdtemp(prefix="uknowapp-dialogues-stage-", dir=data_dir))
        try:
            with zipfile.ZipFile(temp_path) as archive:
                entries = archive.infolist()
                if len(entries) > 100000 or sum(item.file_size for item in entries) > MAX_UNPACKED_ARCHIVE_BYTES:
                    raise HTTPException(status_code=413, detail="Содержимое архива слишком велико")
                names = {item.filename for item in entries}
                if not {"manifest.json", "messages.json", "personal_messages.json"}.issubset(names):
                    raise HTTPException(status_code=400, detail="Это не архив переписок UknowApp")
                for item in entries:
                    name = item.filename
                    if name.startswith("/") or ".." in PurePosixPath(name).parts:
                        raise HTTPException(status_code=400, detail="Архив содержит небезопасный путь")
                manifest = json.loads(archive.read("manifest.json"))
                if manifest.get("format") != ARCHIVE_FORMAT:
                    raise HTTPException(status_code=400, detail="Версия архива не поддерживается")
                for item in entries:
                    if item.filename.startswith("media/") and not item.is_dir():
                        relative = _safe_relative(item.filename[6:])
                        destination = (stage / "media" / relative).resolve()
                        if stage.resolve() not in destination.parents:
                            raise HTTPException(status_code=400, detail="Недопустимый путь к медиафайлу")
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        with archive.open(item) as source, destination.open("wb") as target:
                            shutil.copyfileobj(source, target)
                messages = json.loads(archive.read("messages.json"))
                personal_messages = json.loads(archive.read("personal_messages.json"))
            if not isinstance(messages, list) or not isinstance(personal_messages, list):
                raise HTTPException(status_code=400, detail="Некорректная структура архива")
            conversation_ids = {row[0] for row in db.query(Conversation.id).all()}
            personal_ids = {row[0] for row in db.query(PersonalConversation.id).all()}
            user_ids = {row[0] for row in db.query(User.id).all()}
            if any(int(item["conversation_id"]) not in conversation_ids for item in messages):
                raise HTTPException(status_code=409, detail="В базе отсутствуют переписки из архива. Сначала восстановите базу данных.")
            if any(int(item["conversation_id"]) not in personal_ids for item in personal_messages):
                raise HTTPException(status_code=409, detail="В базе отсутствуют личные диалоги из архива. Сначала восстановите базу данных.")
            if any(item.get("sender_id") is not None and int(item["sender_id"]) not in user_ids for item in messages + personal_messages):
                raise HTTPException(status_code=409, detail="В базе отсутствуют пользователи из архива. Сначала восстановите базу данных.")
            old_rows = db.scalars(select(Message)).all()
            for item in messages:
                metadata = json.loads(item.get("metadata_json") or "{}")
                relative = (metadata.get("media") or {}).get("local_path")
                if relative:
                    source = (stage / "media" / _safe_relative(relative)).resolve()
                    if stage.resolve() not in source.parents or not source.is_file():
                        metadata["media"].pop("local_path", None)
                        metadata["media"]["archive_status"] = "missing_in_archive"
                        item["metadata_json"] = json.dumps(metadata, ensure_ascii=False)
                item["created_at"] = _parse_datetime(item.get("created_at"))
            for item in personal_messages:
                for field in ("created_at", "admin_read_at", "participant_read_at"):
                    item[field] = _parse_datetime(item.get(field))
            db.query(Message).delete(synchronize_session=False)
            db.query(PersonalMessage).delete(synchronize_session=False)
            try:
                db.bulk_insert_mappings(Message, messages)
                db.bulk_insert_mappings(PersonalMessage, personal_messages)
                db.commit()
            except Exception:
                db.rollback()
                raise
            publish_chat_update(0)
            for row in old_rows:
                delete_message_media(row.metadata_json)
            for item in messages:
                metadata = json.loads(item.get("metadata_json") or "{}")
                relative = (metadata.get("media") or {}).get("local_path")
                if not relative:
                    continue
                relative_path = _safe_relative(relative)
                source = (stage / "media" / relative_path).resolve()
                if source.is_file():
                    destination = (MEDIA_DIR / relative_path).resolve()
                    if MEDIA_DIR.resolve() not in destination.parents:
                        continue
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, destination)
            return {"ok": True, "messages": len(messages), "personal_messages": len(personal_messages)}
        finally:
            shutil.rmtree(stage, ignore_errors=True)
    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="Файл не является корректным ZIP-архивом")
    finally:
        temp_path.unlink(missing_ok=True)
        await file.close()


@router.delete("/dialogues")
def cleanup_dialogues(days: int, _: Admin, db: Session = Depends(_get_db)):
    if days not in {30, 60, 120}:
        raise HTTPException(status_code=400, detail="Выберите срок 30, 60 или 120 дней")
    cutoff = datetime.now(UTC) - timedelta(days=days)
    old_rows = db.scalars(select(Message).where(Message.created_at < cutoff)).all()
    old_personal_rows = db.scalars(select(PersonalMessage).where(PersonalMessage.created_at < cutoff)).all()
    deleted_messages = len(old_rows)
    deleted_personal = len(old_personal_rows)
    changed_conversation_ids = {row.conversation_id for row in old_rows}
    changed_personal_ids = {row.conversation_id for row in old_personal_rows}
    db.query(PersonalMessage).filter(PersonalMessage.created_at < cutoff).delete(synchronize_session=False)
    db.query(Message).filter(Message.created_at < cutoff).delete(synchronize_session=False)
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
        "ok": True, "days": days, "deleted_messages": deleted_messages,
        "deleted_personal_messages": deleted_personal, "deleted_media_files": deleted_files,
    }
