"""Administration: stats."""

import contextlib
import json
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.event_hub import publish_chat_update
from app.infrastructure.storage.database_info import database_storage_details
from app.infrastructure.storage.media import delete_message_media
from app.models import (
    Assignment,
    ConnectionCode,
    Conversation,
    ExternalEndpoint,
    Message,
    MessengerAccount,
    PanelSession,
    PersonalConversation,
    PersonalMessage,
    User,
)

from . import common
from .common import Admin
from .restore import restore_state

router = APIRouter()


@router.get("/stats")
def data_stats(_: Admin):
    database_engine, database_size, database_free = database_storage_details()

    with common.SessionLocal() as db:
        users = db.query(User).all()
        assignments = db.query(Assignment).all()
        media_counts = {"images": 0, "audio": 0, "videos": 0, "other": 0}
        for row in db.query(Message.metadata_json).all():
            try:
                # Ошибочные старые метаданные не должны ломать статистику.
                metadata = json.loads(row[0] or "{}")
                if not isinstance(metadata, dict):
                    continue
                media = metadata.get("media")
                if not isinstance(media, dict):
                    continue
                relative = media.get("local_path")
                if not relative:
                    continue
                path = (common.MEDIA_DIR / common.safe_relative(relative)).resolve()
                if common.MEDIA_DIR.resolve() not in path.parents or not path.is_file():
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
            "restore": restore_state(common.DATA_DIR),
            "database_bytes": database_size,
            "database_free_bytes": database_free,
            "database_used_bytes": (
                database_size - database_free
                if database_size is not None and database_free is not None else None
            ),
            "database_engine": database_engine,
            "database_backups_supported": database_engine == "sqlite",
            "media_bytes": common.folder_size(common.MEDIA_DIR),
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
            "external_endpoints": db.query(ExternalEndpoint).count(),
            "messenger_accounts": db.query(MessengerAccount).count(),
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


@router.delete("/dialogues")
def cleanup_dialogues(days: int, _: Admin, db: Annotated[Session, Depends(common.get_db)]):
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
    media_root = common.MEDIA_DIR.resolve()
    for row in old_rows:
        relative = (json.loads(row.metadata_json or "{}").get("media") or {}).get("local_path")
        if relative:
            target = (media_root / common.safe_relative(relative)).resolve()
            if media_root in target.parents and target.is_file():
                deleted_files += 1
        delete_message_media(row.metadata_json)
    if common.MEDIA_DIR.exists():
        for path in sorted(common.MEDIA_DIR.rglob("*"), reverse=True):
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
