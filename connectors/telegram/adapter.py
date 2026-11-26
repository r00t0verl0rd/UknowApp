"""Telegram-specific UI, provider media and API. No imports from Core."""
import asyncio
import logging
import os
from collections import OrderedDict
from pathlib import Path
from urllib.parse import quote

import aiohttp
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramNotFound, TelegramRetryAfter
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.types import URLInputFile
from .teacher_panel import TeacherPanel

from connectors.common.commands import Commands
from connectors.common.client import DeliveryRejected, RetryLater, RpcError

logger = logging.getLogger(__name__)
ATTACHMENT_LIMITS = {"cloud": 20 * 1024 ** 2, "local": 888 * 1024 ** 2}
MEDIA_KINDS = ("photo", "document", "audio", "video", "voice", "video_note", "sticker", "animation")
MESSAGE_KINDS = (*MEDIA_KINDS, "contact", "location", "poll")
MEDIA_NAMES = {"photo": "photo.jpg", "video": "video.mp4", "voice": "voice.ogg",
               "audio": "audio.mp3", "animation": "animation.mp4",
               "video_note": "video.mp4", "sticker": "sticker.webp"}
MEDIA_TYPES = {"photo": "image/jpeg", "video": "video/mp4", "voice": "audio/ogg",
               "audio": "audio/mpeg", "animation": "video/mp4",
               "video_note": "video/mp4", "sticker": "image/webp"}


def split_text(text, limit):
    """Keep every code point; count supplementary characters as two UTF-16 units."""
    parts, start, used = [], 0, 0
    for index, char in enumerate(text):
        width = 2 if ord(char) > 0xFFFF else 1
        if used + width > limit:
            parts.append(text[start:index])
            start, used, limit = index, 0, 4096
        used += width
    return parts + [text[start:]]


class TelegramAdapter:
    def __init__(self, http, token):
        self.http = http
        self.token = token
        mode = os.getenv("TELEGRAM_API_MODE", "cloud")
        if mode not in ATTACHMENT_LIMITS:
            raise ValueError("invalid Telegram API mode")
        self.local = mode == "local"
        self.max_attachment_bytes = ATTACHMENT_LIMITS[mode]
        self.base = (os.getenv("TELEGRAM_API_URL", "http://telegram-bot-api:8081")
                     if self.local else "https://api.telegram.org").rstrip("/")
        self.files = Path(os.getenv("TELEGRAM_FILES_DIR", "/var/lib/telegram-bot-api")).resolve()
        self.bot = Bot(token, session=AiohttpSession(api=TelegramAPIServer.from_base(self.base, is_local=self.local)))
        self.teacher_panel = TeacherPanel(self.bot)
        self.file_ids = OrderedDict()
        self.media_locks = {}

    async def close(self):
        await self.bot.session.close()

    async def chunks(self, path):
        if not path or ".." in Path(path).parts:
            raise ValueError("invalid provider path")
        if self.local:
            source = (self.files / path).resolve()
            if not source.is_relative_to(self.files) or not source.is_file() or source.stat().st_size > self.max_attachment_bytes:
                raise ValueError("invalid local media")
            with source.open("rb") as stream:
                while chunk := await asyncio.to_thread(stream.read, 65536):
                    yield chunk
        else:
            async with self.http.get(f"{self.base}/file/bot{self.token}/{quote(path, safe='/')}",
                                     allow_redirects=False) as response:
                response.raise_for_status()
                total = 0
                async for chunk in response.content.iter_chunked(65536):
                    total += len(chunk)
                    if total > self.max_attachment_bytes:
                        raise ValueError("media too large")
                    yield chunk

    async def delete(self, job):
        try:
            await self.bot.delete_message(chat_id=int(job["chat_id"]), message_id=int(job["external_message_id"]))
        except TelegramRetryAfter as exc:
            raise RetryLater(exc.retry_after) from exc
        except TelegramBadRequest as exc:
            if "message to delete not found" not in str(exc).lower():
                raise DeliveryRejected("provider refused deletion") from exc
        except (TelegramForbiddenError, TelegramNotFound) as exc:
            raise DeliveryRejected("provider refused deletion") from exc

    async def send(self, job, gateway):
        try:
            text = job["text"]
            if not job.get("media") and job.get("kind") != "text":
                text += "\n[" + job["kind"] + "]"
            parts = split_text(text, 1024 if job.get("media") else 4096)
            if len(parts) == 1:
                return await self._send({**job, "text": text}, gateway)
            ids = []
            for index, part in enumerate(parts):
                payload = {**job, "text": part}
                if index:
                    payload.update(media=None, kind="text")
                ident = await self._send(payload, gateway)
                ids.append(str(ident))
                # Save each known copy before attempting the next one.
                gateway.spool.record_delivery_part(job["id"], str(ident))
            return ids
        except TelegramRetryAfter as exc:
            raise RetryLater(exc.retry_after) from exc
        except (TelegramBadRequest, TelegramForbiddenError, TelegramNotFound) as exc:
            # Do not log message text, recipient IDs, or credentials. Distinguish
            # topic configuration failures from private-chat permission failures.
            error = str(exc).lower()
            reason = next((name for needle, name in (
                ("message thread not found", "thread_not_found"),
                ("topic_closed", "topic_closed"),
                ("topic closed", "topic_closed"),
                ("chat not found", "chat_not_found"),
                ("bot was blocked", "bot_blocked"),
                ("not enough rights", "insufficient_rights"),
            ) if needle in error), type(exc).__name__)
            logger.warning("Telegram delivery rejected endpoint=%s reason=%s",
                           "group" if job.get("thread_id") else "private", reason)
            raise DeliveryRejected("provider refused delivery") from exc

    async def _send(self, job, gateway):
        kwargs = {"chat_id": int(job["chat_id"])}
        if job.get("thread_id"):
            kwargs["message_thread_id"] = int(job["thread_id"])
        text = job["text"]
        if not job.get("media"):
            sent = await self.bot.send_message(text=text, **kwargs)
            return sent.message_id
        media = job["media"]
        size = media.get("file_size")
        if isinstance(size, int) and size > self.max_attachment_bytes:
            raise DeliveryRejected("attachment exceeds Telegram mode limit")
        kind = job.get("kind")
        method, field = {"photo": (self.bot.send_photo, "photo"),
                         "video": (self.bot.send_video, "video"),
                         "voice": (self.bot.send_voice, "voice"),
                         "audio": (self.bot.send_audio, "audio"),
                         "animation": (self.bot.send_animation, "animation")}.get(
                            kind, (self.bot.send_document, "document"))

        async def send_file(file):
            return await method(**kwargs, **{field: file}, caption=text, request_timeout=300)

        def upload():
            return URLInputFile(gateway.media_url(job["id"]), headers=gateway.headers,
                                filename=media["file_name"], timeout=300)

        key = (media.get("key"), field)
        if not key[0]:
            return (await send_file(upload())).message_id
        # Cache only provider IDs, never duplicate the permanent Core archive.
        # One in-flight upload per immutable archive key and media type.
        entry = self.media_locks.setdefault(key, [asyncio.Lock(), 0])
        entry[1] += 1
        try:
            async with entry[0]:
                cached = self.file_ids.get(key)
                if cached:
                    try:
                        sent = await send_file(cached)
                        self.file_ids.move_to_end(key)
                        return sent.message_id
                    except TelegramBadRequest as exc:
                        error = str(exc).lower()
                        if not any(s in error for s in ("wrong file identifier", "file reference", "file_id")):
                            raise
                        self.file_ids.pop(key, None)
                sent = await send_file(upload())
                value = getattr(sent, field, None)
                if isinstance(value, list):
                    value = value[-1] if value else None
                file_id = getattr(value, "file_id", None)
                if file_id:
                    self.file_ids[key] = file_id
                    self.file_ids.move_to_end(key)
                    while len(self.file_ids) > 1024:
                        self.file_ids.popitem(last=False)
                return sent.message_id
        finally:
            entry[1] -= 1
            if entry[1] == 0:
                self.media_locks.pop(key, None)


    async def show_menu(self, chat, view, gateway, spool, page=0, force=False):
        account = view.get("account")
        if not account:
            await self.bot.send_message(chat, "Аккаунт ещё не подключён. Попросите администратора UknowSchool подключить Вас")
        elif account["role"] == "student":
            items = view["conversations"]
            await self.bot.send_message(chat, "Ваш преподаватель: " + items[0]["name"] if items else "Пока нет назначенного преподавателя.")
        elif account["role"] == "teacher":
            await self.teacher_panel.refresh(str(chat), gateway, spool, page=page, force=force, view=view)
        else:
            await self.bot.send_message(chat, "Управление доступно в веб-панели.")

    async def refresh_panel(self, actor, gateway, spool, background=False):
        await self.teacher_panel.refresh(actor, gateway, spool, background=background)

    @staticmethod
    def member_present(status, is_member=False):
        return str(status) in {"member", "administrator", "creator"} or (
            str(status) == "restricted" and bool(is_member))

    async def forum_admin(self, chat, actor):
        # Checking the inviter must not require administrator rights on the bot.
        try:
            admins = await self.membership_lookup(self.bot.get_chat_administrators, int(chat))
        except (TelegramBadRequest, TelegramForbiddenError, TelegramNotFound):
            return False
        return any(member.user.id == int(actor) for member in admins or ())

    async def membership_lookup(self, method, *args):
        # Respect Telegram's delay at the current lookup, not by restarting a scan.
        for attempt in range(3):
            try:
                return await method(*args)
            except TelegramRetryAfter as exc:
                if attempt == 2 or exc.retry_after > 60:
                    return None
                await asyncio.sleep(max(1, exc.retry_after))

    async def bind_forum_student(self, chat, thread, gateway):
        # Bot API cannot enumerate group members. Check known linked IDs against
        # Telegram membership, including students who did not send any message.
        info = await self.bot.me()
        try:
            own_member = await self.membership_lookup(self.bot.get_chat_member, int(chat), info.id)
        except (TelegramBadRequest, TelegramForbiddenError, TelegramNotFound):
            return "membership_unavailable"
        if own_member is None:
            return "rate_limited"
        is_admin = str(own_member.status) in {"administrator", "creator"}
        if not self.member_present(own_member.status, getattr(own_member, "is_member", False)) or (
            not is_admin and not getattr(info, "can_read_all_group_messages", False)
        ):
            return "group_access_unavailable"
        match = None
        after = 0
        while True:
            page = await gateway.rpc("endpoint.student_candidates", after=after)
            for actor in page["actors"]:
                try:
                    member = await self.membership_lookup(self.bot.get_chat_member, int(chat), int(actor))
                except (TelegramBadRequest, TelegramForbiddenError, TelegramNotFound) as exc:
                    # For a regular bot, an inaccessible user is not proof of
                    # absence. Never guess a unique student from partial results.
                    if is_admin and isinstance(exc, TelegramBadRequest) and (
                        "user not found" in str(exc).lower() or "user_not_participant" in str(exc).lower()
                    ):
                        continue
                    return "membership_unavailable"
                if member is None:
                    return "rate_limited"
                if self.member_present(member.status, getattr(member, "is_member", False)):
                    if match is not None:
                        return "ambiguous"
                    match = actor
            after = page.get("next")
            if after is None:
                break
        if match is None:
            return "no_student"
        return await self.bind_student(chat, thread, match, gateway)

    @staticmethod
    async def bind_student(chat, thread, actor, gateway):
        try:
            result = await gateway.rpc("endpoint.bind", actor=actor, chat_id=chat,
                                       thread_id=thread)
        except RpcError as exc:
            if exc.code in {403, 409}:
                return "unavailable"
            raise
        return "bound" if result.get("bound") else result.get("reason", "unavailable")

    async def bind_invited_topic(self, chat, thread, gateway, spool, members=None):
        if members is None:
            result = await self.bind_forum_student(chat, thread, gateway)
        else:
            # Core validates a single join directly; resolve only ambiguous batches.
            actors = list(dict.fromkeys(str(m["id"]) for m in members
                                       if m.get("id") and not m.get("is_bot")))
            if len(actors) > 1:
                actors = [actor for actor in actors if ((
                    await gateway.rpc("account.resolve", actor=actor, group=True)
                ).get("account") or {}).get("role") == "student"]
            if len(actors) != 1:
                return
            result = await self.bind_student(chat, thread, actors[0], gateway)
        if result in {"bound", "topic_locked"}:
            if spool:
                spool.forget_forum_topic(chat)
            logger.info("Telegram automatic topic binding: %s", result)
        else:
            logger.info("Telegram automatic topic binding deferred: %s", result)

    @staticmethod
    def forum_thread(message):
        # A reply chain in General is not a forum topic.
        if not message.get("is_topic_message"):
            return None
        thread = message.get("message_thread_id")
        if not thread:
            reply = message.get("reply_to_message") or {}
            if ((reply.get("chat") or {}).get("id") == message["chat"]["id"]
                    and (reply.get("is_topic_message") or reply.get("forum_topic_created"))):
                thread = reply.get("message_thread_id")
        return str(thread) if thread and str(thread) != "1" else None

    @staticmethod
    def inbound_route(update):
        message = update.get("message") or update.get("callback_query") or update.get("my_chat_member") or update.get("chat_member") or {}
        actor = str((message.get("from") or {}).get("id") or "unknown")
        chat = message.get("chat") or {}
        # Preserve the order of incoming messages in each forum.
        if chat.get("type") == "supergroup":
            actor = "group:" + str(chat["id"])
        heavy = any(message.get(k) for k in MEDIA_KINDS)
        return actor, heavy

    async def handle(self, event_id, update, gateway, spool):
        try:
            await self._handle(event_id, update, gateway, spool)
        except TelegramRetryAfter as exc:
            raise RetryLater(exc.retry_after) from exc
        except (TelegramBadRequest, TelegramForbiddenError, TelegramNotFound) as exc:
            raise DeliveryRejected("provider refused inbound action") from exc

    async def _handle(self, event_id, update, gateway, spool):
        own = update.get("my_chat_member")
        membership = own or update.get("chat_member")
        if membership:
            chat = membership.get("chat") or {}
            old = membership.get("old_chat_member") or {}
            new = membership.get("new_chat_member") or {}
            status = new.get("status")
            if own and chat.get("type") == "supergroup":
                logger.info("Telegram bot membership: forum=%s old=%s new=%s",
                            bool(chat.get("is_forum")), old.get("status"), status)
            if not (spool and chat.get("type") == "supergroup" and chat.get("is_forum")):
                return
            chat_id = str(chat["id"])
            if own and status in {"left", "kicked"}:
                spool.forget_forum_topic(chat_id)
            elif (thread := spool.forum_topic(chat_id)) and self.member_present(status, new.get("is_member")):
                if own or not self.member_present(old.get("status"), old.get("is_member")):
                    await self.bind_invited_topic(chat_id, thread, gateway, spool,
                                                  members=None if own else [new.get("user") or {}])
            return
        commands = Commands(gateway, spool)
        # Old inline keyboards are no longer produced. Acknowledge old clicks
        # without interpreting their stale conversation IDs.
        if callback := update.get("callback_query"):
            await self.bot.answer_callback_query(callback["id"], text="Меню обновилось. Нажмите /start.")
            return
        message = update.get("message")
        if not message or not message.get("from") or message["from"].get("is_bot"):
            return
        actor = str(message["from"]["id"])
        chat = str(message["chat"]["id"])
        group = message["chat"]["type"] != "private"
        thread = self.forum_thread(message) if group else (
            str(message["message_thread_id"]) if message.get("message_thread_id") else None
        )
        forum = group and message["chat"]["type"] == "supergroup" and (
            message["chat"].get("is_forum") or message.get("is_topic_message")
        )
        text = message.get("text") or message.get("caption") or ""
        command = text.split(maxsplit=1)[0].split("@")[0] if text else ""
        if forum:
            # A topic creation or edit does not mean this bot was invited there.
            if (message.get("forum_topic_created") or message.get("forum_topic_edited")
                    or message.get("pinned_message")):
                return
            members = message.get("new_chat_members")
            if members:
                if any(member.get("is_bot") for member in members):
                    info = await self.bot.me()
                    if any(member.get("id") == info.id for member in members):
                        logger.info("Telegram bot invitation: has_thread=%s general=%s topic=%s anonymous=%s",
                                    bool(message.get("message_thread_id") or thread),
                                    str(message.get("message_thread_id")) == "1", bool(message.get("is_topic_message")),
                                    bool(message.get("sender_chat")))
                        if (thread and not message.get("sender_chat")
                                and await self.forum_admin(chat, actor)):
                            if spool:
                                spool.remember_forum_topic(chat, thread)
                            logger.info("Telegram invitation topic verified; discovering student")
                            await self.bind_invited_topic(chat, thread, gateway, spool)
                        else:
                            logger.info("Telegram bot invitation has no verified topic")
                        return
                known = spool.forum_topic(chat) if spool else None
                if known:
                    await self.bind_invited_topic(chat, known, gateway, spool, members=members)
                return
        if command == "/bind_group":
            return  # Never forward a legacy setup command as homework.
        invited = None
        if group:
            if (not forum or message.get("sender_chat") or command in {"/start", "/menu"}
                    or not (text or any(message.get(kind) for kind in MESSAGE_KINDS))):
                return
            if not thread:
                logger.info("Telegram forum message ignored: missing topic ID")
                return
            invited = spool.forum_topic(chat) if spool else None
            if invited and invited != thread:
                logger.info("Telegram forum message ignored: pending invitation topic mismatch")
                return
        if not group and command in {"/start", "/menu"}:
            commands.clear(actor)
            await self.show_menu(int(chat), await commands.menu(actor), gateway, spool, force=True)
            return
        route = {"chat_id": chat, "thread_id": thread} if group else {}
        view = await gateway.rpc("account.resolve", actor=actor, group=group, **route)
        if group and view.get("route_allowed") is False:
            logger.info("Telegram forum message ignored: %s", view.get("route_reason", "route unavailable"))
            return
        account = view.get("account")
        if group and (account or {}).get("role") != "student":
            return
        if account is None:
            result = await commands.bind(actor, chat, text, message["from"].get("username"))
            await self.show_menu(int(chat), result or view, gateway, spool)
            return
        if account["role"] not in {"teacher", "student"}:
            return
        if account["role"] == "teacher" and not group and message.get("text"):
            if await self.teacher_panel.action(actor, message["message_id"], text, view, gateway, spool):
                return
        selection = commands.selection(actor) if account["role"] == "teacher" else None
        if account["role"] == "teacher" and selection not in {c["id"] for c in view["conversations"]}:
            commands.clear(actor)
            await self.show_menu(int(chat), view, gateway, spool)
            return
        if account["role"] == "student" and not view["conversations"]:
            await self.bot.send_message(int(chat), "Пока нет назначенного преподавателя.")
            return
        event = {"id": event_id, "external_message_id": str(message["message_id"]), "actor": actor, "chat_id": chat, "thread_id": thread,
                 "channel": "group" if group else "private", "conversation_id": selection,
                 "text": text, "kind": "text"}
        if invited == thread and invited:
            event["pending_topic"] = True
        for kind in MEDIA_KINDS:
            value = message.get(kind)
            if not value:
                continue
            if isinstance(value, list):
                value = value[-1]
            event["kind"] = kind
            if (value.get("file_size") or 0) > self.max_attachment_bytes:
                event["media_unavailable"] = True
                break
            try:
                remote = await self.bot.get_file(value["file_id"])
            except (TelegramBadRequest, TelegramForbiddenError, TelegramNotFound):
                event["media_unavailable"] = True
                break
            if remote.file_size is None or remote.file_size > self.max_attachment_bytes or not remote.file_path:
                event["media_unavailable"] = True
                break
            name = value.get("file_name") or MEDIA_NAMES.get(kind, "attachment")
            mime = value.get("mime_type") or MEDIA_TYPES.get(kind)
            await gateway.upload(event_id, self.chunks(remote.file_path))
            event["media"] = {"file_name": name, "mime_type": mime}
            break
        else:
            if message.get("contact"):
                event["kind"] = "contact"
            elif message.get("location"):
                event["kind"] = "location"
                event["location"] = {k: message["location"][k] for k in ("latitude", "longitude")}
            elif message.get("poll"):
                event["kind"] = "poll"
                event["poll"] = {"question": message["poll"]["question"], "options": [o["text"] for o in message["poll"]["options"]]}
            elif not text:
                event["kind"] = "unsupported"
        await gateway.inbound(event)
