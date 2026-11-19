"""HTTP API веб-панели: авторизация, участники, переписки и доставка сообщений."""

import asyncio
import hashlib
import json
import logging
import secrets
import mimetypes
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from aiogram.types import BufferedInputFile
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import selectinload
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ...config import ADMIN_USERNAME, VAPID_PUBLIC_KEY
from ...event_hub import publish_chat_update, subscribe_chat_updates, unsubscribe_chat_updates
from ...modules.media.service import MEDIA_DIR, delete_message_media, safe_media_type, media_content_disposition
from ...models import Assignment, ConnectionCode, Conversation, Message, PanelSession, PersonalConversation, PersonalMessage, StudentTelegramGroup, TeacherPanel, TeacherSession, User, PushSubscription
from ...schemas import AssignmentCreate, LoginRequest, PanelMessageCreate, PersonalConversationCreate, PersonalMessageCreate, UserCreate, UserUpdate
from ...security import (
    authenticate_panel_user,
    check_login_rate_limit,
    clear_panel_cookies,
    clear_username_failures,
    create_panel_session,
    hash_web_password,
    record_failed_login,
    revoke_panel_session,
    verify_request_origin,
)
from ...telegram_common import text_contains_contact_data
from ...push_notifications import schedule_push
from ...modules.users.service import user_dict, generate_panel_access_code, validate_panel_username
from ...modules.conversations.service import conversation_dict, conversation_dicts
from ...modules.personal_chat.service import _personal_conversation, _personal_conversation_dict
from ...modules.assignments.service import assign_student
from ...modules.messaging.service import _panel_visible_conversation, _panel_message_dict



from ..dependencies import Admin, PanelUser, Db


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


