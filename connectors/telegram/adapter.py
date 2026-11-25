"""Telegram-specific UI, provider media and API. No imports from Core."""
import asyncio
import logging
import os
from pathlib import Path
from urllib.parse import quote

import aiohttp
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramNotFound
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, URLInputFile

from connectors.common.commands import Commands
from connectors.common.client import DeliveryRejected, RpcError

logger = logging.getLogger(__name__)
MAX_BYTES = 1024 ** 3


class TelegramAdapter:
    def __init__(self, http, token):
        self.http = http
        self.token = token
        mode = os.getenv("TELEGRAM_API_MODE", "cloud")
        if mode not in {"cloud", "local"}:
            raise ValueError("invalid Telegram API mode")
        self.local = mode == "local"
        self.base = (os.getenv("TELEGRAM_API_URL", "http://telegram-bot-api:8081")
                     if self.local else "https://api.telegram.org").rstrip("/")
        self.files = Path(os.getenv("TELEGRAM_FILES_DIR", "/var/lib/telegram-bot-api")).resolve()
        self.bot = Bot(token, session=AiohttpSession(api=TelegramAPIServer.from_base(self.base, is_local=self.local)))

    async def close(self):
        await self.bot.session.close()

    async def chunks(self, path):
        if not path or ".." in Path(path).parts:
            raise ValueError("invalid provider path")
        if self.local:
            source = (self.files / path).resolve()
            if not source.is_relative_to(self.files) or not source.is_file() or source.stat().st_size > MAX_BYTES:
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
                    if total > MAX_BYTES:
                        raise ValueError("media too large")
                    yield chunk

    async def delete(self, job):
        try:
            await self.bot.delete_message(chat_id=int(job["chat_id"]), message_id=int(job["external_message_id"]))
        except TelegramBadRequest as exc:
            if "message to delete not found" not in str(exc).lower():
                raise DeliveryRejected("provider refused deletion") from exc
        except (TelegramForbiddenError, TelegramNotFound) as exc:
            raise DeliveryRejected("provider refused deletion") from exc

    async def send(self, job, gateway):
        try:
            return await self._send(job, gateway)
        except (TelegramBadRequest, TelegramForbiddenError, TelegramNotFound) as exc:
            raise DeliveryRejected("provider refused delivery") from exc

    async def _send(self, job, gateway):
        kwargs = {"chat_id": int(job["chat_id"])}
        if job.get("thread_id"):
            kwargs["message_thread_id"] = int(job["thread_id"])
        text = job["text"]
        if not job.get("media"):
            if job.get("kind") != "text":
                text += "\n[" + job["kind"] + "]"
            sent = await self.bot.send_message(text=text[:4096], **kwargs)
            return sent.message_id
        media = job["media"]
        file = URLInputFile(gateway.media_url(job["id"]), headers=gateway.headers,
                            filename=media["file_name"], timeout=300)
        kind = job.get("kind")
        method, field = {"photo": (self.bot.send_photo, "photo"),
                         "video": (self.bot.send_video, "video"),
                         "voice": (self.bot.send_voice, "voice"),
                         "audio": (self.bot.send_audio, "audio"),
                         "animation": (self.bot.send_animation, "animation")}.get(
                            kind, (self.bot.send_document, "document"))
        sent = await method(**kwargs, **{field: file}, caption=text[:1024], request_timeout=300)
        return sent.message_id

    async def show_menu(self, chat, view, page=0):
        account = view.get("account")
        if not account:
            await self.bot.send_message(chat, "Аккаунт ещё не подключён. Попросите администратора UknowSchool подключить Вас")
            return
        if account["role"] == "student":
            items = view["conversations"]
            text = "Ваш преподаватель: " + items[0]["name"] if items else "Пока нет назначенного преподавателя."
            await self.bot.send_message(chat, text)
            return
        if account["role"] != "teacher":
            await self.bot.send_message(chat, "Управление доступно в веб-панели.")
            return
        items = view["conversations"]
        page = min(max(0, page), max(0, (len(items) - 1) // 12))
        buttons = [[InlineKeyboardButton(text=(f'{c["name"]} ({c["unread"]})')[:64],
                                          callback_data=f'chat:{c["id"]}')]
                   for c in items[page * 12:(page + 1) * 12]]
        nav = []
        if page:
            nav.append(InlineKeyboardButton(text="←", callback_data=f"page:{page-1}"))
        if (page + 1) * 12 < len(items):
            nav.append(InlineKeyboardButton(text="→", callback_data=f"page:{page+1}"))
        if nav:
            buttons.append(nav)
        await self.bot.send_message(chat, "Выберите диалог:" if buttons else "Нет активных диалогов.",
                                    reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons) if buttons else None)

    async def show_chat(self, chat, view):
        lines = [view["name"]]
        for m in view["messages"]:
            lines.append(m["name"] + ": " + (m["text"] or "[" + m["kind"] + "]"))
        await self.bot.send_message(chat, "\n".join(lines)[:3900] + "\n\nНапишите ответ.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="К списку", callback_data="menu")]]))

    async def group_allowed(self, message):
        chat = message["chat"]
        if chat.get("type") != "supergroup" or not chat.get("is_forum") or not message.get("message_thread_id"):
            return False
        info = await self.bot.me()
        if info.can_read_all_group_messages:
            return True
        member = await self.bot.get_chat_member(chat["id"], info.id)
        return str(member.status) in {"administrator", "creator"}

    async def handle(self, event_id, update, gateway, spool):
        commands = Commands(gateway, spool)
        callback = update.get("callback_query")
        if callback:
            actor = str(callback["from"]["id"])
            chat = (callback.get("message") or {}).get("chat") or {}
            if chat.get("type") != "private" or str(chat.get("id")) != actor:
                return
            data = callback.get("data") or ""
            try:
                if data.startswith(("chat:", "reply:", "ui:chat:", "ui:reply:")):
                    view = await commands.open(actor, int(data.rsplit(":", 1)[1]))
                    await self.show_chat(int(chat["id"]), view)
                else:
                    commands.clear(actor)
                    page = int(data.rsplit(":", 1)[1]) if "page:" in data else 0
                    await self.show_menu(int(chat["id"]), await commands.menu(actor), page)
            except (ValueError, RpcError) as exc:
                if isinstance(exc, RpcError) and exc.code >= 500:
                    raise
                await self.bot.send_message(int(chat["id"]), "Диалог недоступен.")
            finally:
                try:
                    await self.bot.answer_callback_query(callback["id"])
                except Exception as exc:
                    logger.debug("Callback answer unavailable: %s", type(exc).__name__)
            return
        message = update.get("message")
        if not message or not message.get("from") or message["from"].get("is_bot"):
            return
        actor = str(message["from"]["id"])
        chat = str(message["chat"]["id"])
        group = message["chat"]["type"] != "private"
        thread = str(message["message_thread_id"]) if message.get("message_thread_id") else None
        text = message.get("text") or message.get("caption") or ""
        command = text.split(maxsplit=1)[0].split("@")[0] if text else ""
        if group and not await self.group_allowed(message):
            if command == "/bind_group":
                await self.bot.send_message(int(chat), "Откройте тему и проверьте Group Privacy.", message_thread_id=int(thread) if thread else None)
            return
        if group and command in {"/start", "/menu"}:
            return
        if not group and command in {"/start", "/menu"}:
            commands.clear(actor)
            await self.show_menu(int(chat), await commands.menu(actor))
            return
        view = await gateway.rpc("account.resolve", actor=actor)
        account = view.get("account")
        if account is None:
            if group:
                return
            result = await commands.bind(actor, chat, text, message["from"].get("username"))
            await self.show_menu(int(chat), result or view)
            return
        if command == "/bind_group":
            if group:
                await gateway.rpc("endpoint.bind", actor=actor, chat_id=chat, thread_id=thread)
                await self.bot.send_message(int(chat), "Тема привязана. Сообщения будут приходить сюда и в личный чат с ботом.", message_thread_id=int(thread))
            return
        if account["role"] not in {"teacher", "student"} or (group and account["role"] != "student"):
            return
        selection = commands.selection(actor) if account["role"] == "teacher" else None
        if account["role"] == "teacher" and selection not in {c["id"] for c in view["conversations"]}:
            commands.clear(actor)
            await self.show_menu(int(chat), view)
            return
        if account["role"] == "student" and not view["conversations"]:
            await self.bot.send_message(int(chat), "Пока нет назначенного преподавателя.", message_thread_id=int(thread) if thread else None)
            return
        event = {"id": event_id, "external_message_id": str(message["message_id"]), "actor": actor, "chat_id": chat, "thread_id": thread,
                 "channel": "group" if group else "private", "conversation_id": selection,
                 "text": text, "kind": "text"}
        for kind in ("photo", "document", "audio", "video", "voice", "video_note", "sticker", "animation"):
            value = message.get(kind)
            if not value:
                continue
            if isinstance(value, list):
                value = value[-1]
            event["kind"] = kind
            if (value.get("file_size") or 0) > MAX_BYTES or (not self.local and (value.get("file_size") or 0) > 20 * 1024 ** 2):
                event["media_unavailable"] = True
                break
            remote = await self.bot.get_file(value["file_id"])
            if remote.file_size is None or remote.file_size > MAX_BYTES or not remote.file_path:
                event["media_unavailable"] = True
                break
            name = value.get("file_name") or {"photo":"photo.jpg","video":"video.mp4","voice":"voice.ogg",
                    "audio":"audio.mp3","animation":"animation.mp4","video_note":"video.mp4","sticker":"sticker.webp"}.get(kind,"attachment")
            mime = value.get("mime_type") or {"photo":"image/jpeg","video":"video/mp4","voice":"audio/ogg",
                    "audio":"audio/mpeg","animation":"video/mp4","video_note":"video/mp4","sticker":"image/webp"}.get(kind)
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
