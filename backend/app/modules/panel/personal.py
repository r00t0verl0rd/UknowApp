"""HTTP routes for personal chats."""
from typing import Annotated

from fastapi import APIRouter, File, Form, Query, Request, UploadFile

from app.infrastructure.storage.media import attachment_response
from app.modules.dependencies import Db, PanelUser
from app.modules.personal_chat import operations

router = APIRouter()


@router.get("/panel/personal-conversations")
def personal_conversations(principal: PanelUser, db: Db):
    return operations.personal_conversations(principal, db)


@router.post("/panel/personal-conversations", status_code=201)
def create_personal_conversation(payload: dict, principal: PanelUser, db: Db):
    return operations.create_personal_conversation(payload, principal, db)


@router.delete("/panel/personal-conversations/{conversation_id}")
def delete_personal_conversation(conversation_id: int, principal: PanelUser, db: Db):
    return operations.delete_personal_conversation(conversation_id, principal, db)


@router.get("/panel/personal-conversations/{conversation_id}/summary")
def personal_conversation_summary(conversation_id: int, principal: PanelUser, db: Db):
    return operations.personal_conversation_summary(conversation_id, principal, db)


@router.get("/panel/personal-conversations/{conversation_id}/messages")
def personal_messages(conversation_id: int, principal: PanelUser, db: Db, after_id: int = 0,
                   limit: int | None = Query(None, ge=1, le=100), before_id: int | None = None,
                   mark_read: bool = True, forward: bool = False,
                   around_id: int | None = Query(None, ge=1), first_unread: bool = False):
    return operations.personal_messages(conversation_id, principal, db, after_id, limit, before_id, mark_read, forward, around_id, first_unread)


@router.get("/panel/personal-messages/{message_id}")
def personal_message(message_id: int, principal: PanelUser, db: Db):
    return operations.personal_message(message_id, principal, db)


@router.post("/panel/personal-conversations/{conversation_id}/messages", status_code=201)
def send_personal_message(
    conversation_id: int,
    payload: dict,
    principal: PanelUser,
    db: Db,
):
    return operations.send_personal_message(conversation_id, payload, principal, db)


@router.get("/panel/personal-messages/{message_id}/media")
def personal_message_media(message_id: int, request: Request, principal: PanelUser, db: Db):
    path, media = operations.personal_message_media(message_id, principal, db)
    return attachment_response(request, path, media)


@router.post("/panel/personal-conversations/{conversation_id}/attachments", status_code=201)
def send_personal_attachment(
    conversation_id: int,
    principal: PanelUser,
    db: Db,
    file: Annotated[UploadFile, File()],
    text: Annotated[str, Form()] = "",
    client_message_id: Annotated[str | None, Form()] = None,
):
    return operations.send_personal_attachment(conversation_id, principal, db, file, text, client_message_id)


@router.delete("/panel/personal-messages/{message_id}")
def delete_personal_message(message_id: int, principal: PanelUser, db: Db):
    return operations.delete_personal_message(message_id, principal, db)
