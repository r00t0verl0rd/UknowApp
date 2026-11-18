"""Администрирование резервных копий, архива переписок и очистки данных."""

import json
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from .database import SessionLocal, engine
from .event_hub import publish_chat_update
from .media_storage import MEDIA_DIR, delete_message_media
from .models import Conversation, Message, PersonalConversation, PersonalMessage, User
from .security import require_admin

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


@router.get("/stats")
def data_stats(_: Admin):
    database = _database_path()
    database_size = sum(
        item.stat().st_size for item in (
            database, Path(str(database) + "-wal"), Path(str(database) + "-shm")
        ) if item.is_file()
    )
    return {
        "database_bytes": database_size,
        "media_bytes": _folder_size(MEDIA_DIR),
        "messages": _count_rows(Message),
        "personal_messages": _count_rows(PersonalMessage),
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
            "manifest.json": {"format": ARCHIVE_FORMAT, "created_at": datetime.now(timezone.utc).isoformat()},
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
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
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
