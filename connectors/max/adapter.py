"""Local MAX Bot API adapter for private school conversations."""
import asyncio
import json
import time
from urllib.parse import urlsplit

import aiohttp

from connectors.common.client import DeliveryRejected, RetryLater
from connectors.common.commands import (
    CODE, Commands, BACK, REFRESH, PREVIOUS, NEXT, STALE_PANEL, SELECT_RECIPIENT,
    panel_revision, callback_action, recipient_ready, navigation, menu_page,
)
from connectors.common.media_formats import max_inbound_kind, max_upload_kind, delivery_text
from connectors.common.panel_text import teacher_panel_text

API = "https://platform-api2.max.ru"
KINDS = {"image", "video", "audio", "file", "sticker"}


class MaxAdapter:
    def __init__(self, http, token):
        self.http = http
        self.headers = {"Authorization": token}
        self.panel_locks = {}
        self.panel_updated = {}

    async def api(self, method, path, *, params=None, body=None):
        async with self.http.request(method, API + path, params=params, json=body,
                                     headers=self.headers, allow_redirects=False) as response:
            if response.status == 429:
                raise RetryLater(int(response.headers.get("Retry-After", "5")))
            if 400 <= response.status < 500:
                error = await response.json(content_type=None)
                if error.get("code") == "attachment.not.ready":
                    raise RetryLater(5)
                raise DeliveryRejected(f"MAX HTTP {response.status}")
            response.raise_for_status()
            result = await response.json()
            if result.get("success") is False:
                raise DeliveryRejected("MAX rejected operation")
            return result

    async def message(self, actor, text, attachments=None, *, group=False):
        data = {"text": text}
        if attachments:
            data["attachments"] = attachments
        result = await self.api("POST", "/messages", params={"chat_id" if group else "user_id": actor}, body=data)
        return result["message"]["body"]["mid"]

    async def send(self, job, gateway):
        attachments = []
        media = job.get("media")
        if media:
            kind = max_upload_kind(job["kind"], media)
            ticket = await self.api("POST", "/uploads", params={"type": kind})
            async with self.http.get(gateway.media_url(job["id"]), headers=gateway.headers,
                                     allow_redirects=False) as source:
                source.raise_for_status()
                form = aiohttp.FormData()
                form.add_field("data", source.content, filename=media["file_name"],
                               content_type=media.get("mime_type") or "application/octet-stream")
                async with self.http.post(ticket["url"], data=form, allow_redirects=False) as upload:
                    upload.raise_for_status()
                    payload = ({"token": ticket["token"]} if ticket.get("token")
                               else await upload.json(content_type=None))
            attachments.append({"type": kind, "payload": payload})
        text = delivery_text(job)
        ids = []
        for i in range(0, max(1, len(text)), 4000):
            if i:
                await asyncio.sleep(0.6)
            address = job.get("chat_id") or job["recipient"]
            mid = await self.message(address, text[i:i + 4000], attachments if not i else None,
                                     group=address != job["recipient"])
            gateway.spool.record_delivery_part(job["id"], mid)
            ids.append(mid)
        return ids

    async def delete(self, job):
        await self.api("DELETE", "/messages", params={"message_id": job["external_message_id"]})

    def inbound_route(self, update):
        if update.get("update_type") == "message_callback":
            callback = update.get("callback") or {}
            return str((callback.get("user") or {}).get("user_id", "")), False
        message = update.get("message") or {}
        sender = message.get("sender") or update.get("user") or {}
        return str(sender.get("user_id", "")), bool(message.get("body", {}).get("attachments"))

    async def _panel_update_delay(self, actor):
        delay = 0.55 - (time.monotonic() - self.panel_updated.get(actor, 0))
        if delay > 0:
            await asyncio.sleep(delay)
        self.panel_updated[actor] = time.monotonic()

    async def refresh_panel(self, actor, gateway, spool, background=False, page=None,
                            callback_id=None, callback_mid=None, force=False):
        actor = str(actor)
        lock = self.panel_locks.setdefault(actor, asyncio.Lock())
        async with lock:
            await self._refresh_panel(actor, gateway, spool, background, page, callback_id, callback_mid, force)

    async def _refresh_panel(self, actor, gateway, spool, background, page, callback_id, callback_mid, force):
        commands = Commands(gateway, spool)
        result = await commands.panel(actor)
        previous = spool.panel(actor) or {}
        page = previous.get("page", 0) if page is None else page
        role = (result.get("account") or {}).get("role")
        if role != "teacher":
            commands.clear(actor)
            stale = set(previous.get("stale_buttons", []))
            if previous.get("role") in {None, "teacher"} and previous.get("mid"):
                stale.update(previous.get("buttons", []))
                if not previous.get("buttons"):
                    stale.update(await self._legacy_panel_buttons(previous))
            if role == "student":
                items = result.get("conversations") or []
                text = "Ваш преподаватель: " + items[0]["name"] if items else "Пока нет назначенного преподавателя."
            else:
                text = "Управление доступно в веб-панели."
            if callback_id:
                await self._panel_update_delay(actor)
                await self.api("POST", "/answers", params={"callback_id": callback_id},
                               body={"message": {"text": text, "attachments": []}})
                mid = previous.get("mid")
            elif previous.get("mid"):
                await self._panel_update_delay(actor)
                try:
                    await self.api("DELETE", "/messages", params={"message_id": previous["mid"]})
                    mid = await self.message(actor, text)
                except DeliveryRejected:
                    try:
                        await self.api("PUT", "/messages", params={"message_id": previous["mid"]},
                                       body={"text": text, "attachments": []})
                        mid = previous["mid"]
                    except DeliveryRejected:
                        return
            else:
                if background:
                    return
                mid = await self.message(actor, text)
            spool.save_panel(actor, {"mid": mid, "text": text, "page": 0, "role": role,
                                     "buttons": [], "stale_buttons": sorted(stale)})
            return

        chat = result.get("chat")
        if commands.selection(actor) is not None and not chat:
            commands.clear(actor)
        visible, page, total = commands.page(result["conversations"], page)
        buttons = [[{"type": "callback", "text": item["name"].strip(),
                     "payload": f"open:{item['id']}"} for item in visible[i:i + 2]]
                   for i in range(0, len(visible), 2)]
        nav = ([{"type": "callback", "text": PREVIOUS, "payload": "previous"}] if page else [])
        if page + 1 < total:
            nav.append({"type": "callback", "text": NEXT, "payload": "next"})
        if nav:
            buttons.append(nav)
        buttons.append([{"type": "callback", "text": BACK, "payload": "back"},
                        {"type": "callback", "text": REFRESH, "payload": "refresh"}])
        actions = [button["payload"] for row in buttons for button in row]
        revision, state = panel_revision(previous, page, chat, actions)
        for row in buttons:
            for button in row:
                button["payload"] = revision + ":" + button["payload"]
        panel_state = {"revision": revision, "navigation_state": state, "actions": actions,
                       "recipient": (chat or {}).get("id")}
        text = teacher_panel_text(chat, visible, page, total)
        keyboard = [{"type": "inline_keyboard", "payload": {"buttons": buttons}}]
        signature = json.dumps(buttons, ensure_ascii=False, separators=(",", ":"))
        labels = [button["text"] for row in buttons for button in row]
        if callback_id:
            await self._panel_update_delay(actor)
            await self.api("POST", "/answers", params={"callback_id": callback_id},
                           body={"message": {"text": text, "attachments": keyboard}})
            if previous.get("mid"):
                spool.save_panel(actor, {**panel_state, "mid": previous["mid"], "text": text, "page": page,
                                         "role": role, "buttons": labels, "signature": signature})
                return
        elif previous.get("mid") and previous.get("signature") == signature and (background or not force):
            if previous.get("text") == text:
                return
            await self._panel_update_delay(actor)
            try:
                await self.api("PUT", "/messages", params={"message_id": previous["mid"]},
                               body={"text": text, "attachments": keyboard})
                spool.save_panel(actor, {**panel_state, "mid": previous["mid"], "text": text, "page": page,
                                         "role": role, "buttons": labels, "signature": signature})
                return
            except DeliveryRejected:
                if background:
                    return
        if not background or previous.get("mid"):
            await self._panel_update_delay(actor)
            mid = await self.message(actor, text, keyboard)
            spool.save_panel(actor, {**panel_state, "mid": mid, "text": text, "page": page,
                                     "role": role, "buttons": labels, "signature": signature})
            if previous.get("mid") and previous["mid"] != mid:
                try:
                    await self.api("DELETE", "/messages", params={"message_id": previous["mid"]})
                except DeliveryRejected:
                    pass

    @staticmethod
    def _legacy_buttons(text):
        lines = text.splitlines()
        if not lines or not lines[0].startswith("Ваша группа ·"):
            return []
        return [lines[i].split(" · ", 1)[0] for i in range(1, len(lines), 2) if lines[i].strip()]

    async def _legacy_panel_buttons(self, panel):
        labels = self._legacy_buttons(panel.get("text", ""))
        if panel.get("mid") and panel.get("role") is None:
            try:
                message = await self.api("GET", "/messages/" + str(panel["mid"]))
                body = (message.get("message") or message).get("body") or {}
                labels.extend(
                    button.get("text", "")
                    for attachment in body.get("attachments", [])
                    if attachment.get("type") == "inline_keyboard"
                    for row in (attachment.get("payload") or {}).get("buttons", [])
                    for button in row
                )
            except DeliveryRejected:
                pass
        return [label for label in labels if label]

    @classmethod
    def _stale_action(cls, actor, text, spool):
        panel = spool.panel(actor)
        stale = set(panel.get("stale_buttons", []))
        if panel.get("role") == "teacher":
            stale.update(panel.get("buttons", []))
            if not panel.get("buttons"):
                stale.update(cls._legacy_buttons(panel.get("text", "")))
        return bool(text.strip()) and (
            text.strip() in stale or text.strip() in {BACK, REFRESH, PREVIOUS, NEXT}
        )

    async def handle(self, event_id, update, gateway, spool):
        if update.get("update_type") == "message_callback":
            await self.handle_callback(update, gateway, spool)
            return
        actor, _ = self.inbound_route(update)
        message = update.get("message") or {}
        if not actor or message.get("sender", {}).get("is_bot"):
            return
        commands = Commands(gateway, spool)
        if update["update_type"] == "bot_started":
            account = await commands.menu(actor)
            if account.get("account"):
                await self.show_account(actor, account, gateway, spool)
            else:
                await self.message(actor, "Отправьте код входа в школу — панель откроется автоматически.")
            return
        body = message["body"]
        text = body.get("text") or ""
        recipient = message.get("recipient") or {}
        if recipient.get("chat_type") == "chat" and recipient.get("chat_id") is not None:
            chat = str(recipient["chat_id"])
            if CODE.fullmatch(text.replace("-", "").replace(" ", "").upper()):
                return
            if text.strip() == "/bind_school_chat":
                result = await gateway.rpc("endpoint.bind", actor=actor, chat_id=chat)
                if result.get("bound"):
                    await self.message(chat, "Группа подключена к переписке ученика.", group=True)
                return
            route = await gateway.rpc("account.resolve", actor=actor, group=True, chat_id=chat)
            if route.get("route_allowed"):
                await self.forward_parts(event_id, actor, chat, "group", None, body, gateway)
            return
        if recipient.get("chat_type") != "dialog":
            return
        account = await commands.menu(actor)
        if not body.get("attachments") and CODE.fullmatch(text.replace("-", "").replace(" ", "").upper()):
            bound = await commands.bind(actor, actor, text)
            if bound and bound.get("account"):
                commands.clear(actor)
                await self.show_account(actor, bound, gateway, spool)
                return
            if not account["account"]:
                await self.message(actor, "Для подключения отправьте действующий код входа в школу.")
                return
        if not account["account"]:
            bound = await commands.bind(actor, actor, text)
            if not bound or not bound.get("account"):
                await self.message(actor, "Для подключения отправьте действующий код входа в школу.")
                return
            await self.show_account(actor, bound, gateway, spool)
            return
        if account["account"].get("role") != "teacher":
            panel = spool.panel(actor)
            if panel.get("role") != account["account"]["role"]:
                await self.refresh_panel(actor, gateway, spool)
            if self._stale_action(actor, text, spool):
                return
        if not body.get("attachments") and CODE.fullmatch(text.replace("-", "").replace(" ", "").upper()):
            await self.show_account(actor, account, gateway, spool)
            return
        role = account["account"]["role"]
        reset_page = menu_page(text) if not body.get("attachments") else None
        if reset_page is not None:
            commands.clear(actor)
            await self.refresh_panel(actor, gateway, spool, page=reset_page, force=True)
            return
        if role == "teacher" and not body.get("attachments"):
            current = (spool.panel(actor) or {}).get("page", 0)
            action = await navigation(commands, actor, text, account, current)
            if action is not None:
                page, notice = action
                if notice:
                    await self.message(actor, notice)
                await self.refresh_panel(actor, gateway, spool, page=page)
                return
            if self._stale_action(actor, text, spool):
                await self.message(actor, STALE_PANEL)
                await self.refresh_panel(actor, gateway, spool)
                return
        if role == "teacher" and not recipient_ready(spool, actor, account["conversations"]):
            await self.message(actor, SELECT_RECIPIENT)
            await self.refresh_panel(actor, gateway, spool)
            return
        if role == "student" and not account["conversations"]:
            await self.message(actor, "Пока нет назначенного преподавателя.")
            return
        if role not in {"teacher", "student"}:
            return
        selection = commands.selection(actor) if role == "teacher" else None
        await self.forward_parts(event_id, actor, actor, "private", selection, body, gateway)

    async def show_account(self, actor, account, gateway, spool):
        role = account["account"]["role"]
        if role == "teacher":
            await self.refresh_panel(actor, gateway, spool)
        elif role == "student":
            await self.refresh_panel(actor, gateway, spool)
        else:
            await self.message(actor, "Управление доступно в веб-панели.")

    async def handle_callback(self, update, gateway, spool):
        callback = update.get("callback") or {}
        actor = str((callback.get("user") or {}).get("user_id", ""))
        if not actor:
            return
        panel = spool.panel(actor) or {}
        original = callback.get("message") or {}
        mid = (original.get("body") or {}).get("mid")
        payload = callback_action(str(callback.get("payload") or ""), panel)
        if not mid or mid != panel.get("mid") or not payload:
            if callback.get("callback_id"):
                await self.api("POST", "/answers", params={"callback_id": callback["callback_id"]},
                               body={"notification": STALE_PANEL})
            return
        commands = Commands(gateway, spool)
        result = await commands.menu(actor)
        if (spool.panel(actor) or {}).get("revision") != panel.get("revision"):
            if callback.get("callback_id"):
                await self.api("POST", "/answers", params={"callback_id": callback["callback_id"]},
                               body={"notification": STALE_PANEL})
            return
        account = result.get("account") or {}
        page = panel.get("page", 0)
        if account.get("role") == "teacher":
            if payload.startswith("open:"):
                ident = payload[5:]
                choice = next((item for item in result["conversations"]
                               if str(item["id"]) == ident), None)
                if choice:
                    await commands.open(actor, choice["id"])
                    page = result["conversations"].index(choice) // 6
            elif payload == "back":
                commands.clear(actor)
            elif payload == "previous":
                commands.clear(actor)
                page -= 1
            elif payload == "next":
                commands.clear(actor)
                page += 1
        else:
            commands.clear(actor)
        original = callback.get("message") or {}
        mid = (original.get("body") or {}).get("mid")
        await self.refresh_panel(actor, gateway, spool, page=page,
                                 callback_id=callback.get("callback_id"), callback_mid=mid)

    async def forward_parts(self, event_id, actor, chat, channel, selection, body, gateway):
        text = body.get("text") or ""
        parts = body.get("attachments") or [None]
        for index, part in enumerate(parts):
            ident = f"{event_id}.{index}"
            event = {"id": ident, "actor": actor, "chat_id": chat, "channel": channel,
                     "conversation_id": selection, "text": text if index == 0 else "",
                     "external_message_id": body["mid"] + (f".{index}" if index else ""), "kind": "text"}
            if part:
                kind = part["type"]
                if kind in KINDS:
                    payload = part.get("payload") or {}
                    filename = payload.get("filename") or part.get("filename") or ""
                    event["kind"] = max_inbound_kind(kind, "", filename)
                    event["media_unavailable"] = True
                    url = payload.get("url") or ""
                    host = urlsplit(url).hostname or ""
                    trusted = any(host == domain or host.endswith("." + domain)
                                  for domain in ("max.ru", "okcdn.ru", "mycdn.me", "usercontent.max.ru", "vkuser.net")) or host == "i.oneme.ru"
                    if urlsplit(url).scheme == "https" and trusted:
                        async with self.http.get(url, allow_redirects=False) as source:
                            if source.status == 200:
                                try:
                                    await gateway.upload(ident, source.content.iter_chunked(65536))
                                except aiohttp.ClientResponseError as exc:
                                    if exc.status not in {400, 413}:
                                        raise
                                    event["media_unavailable"] = True
                                else:
                                    mime = source.content_type
                                    event["kind"] = max_inbound_kind(kind, mime, filename)
                                    event.pop("media_unavailable", None)
                                    suffix = {"image/jpeg": ".jpg", "image/png": ".png", "image/gif": ".gif",
                                              "image/webp": ".webp", "audio/ogg": ".ogg", "audio/mpeg": ".mp3",
                                              "audio/mp4": ".m4a", "video/mp4": ".mp4"}.get(mime, "")
                                    event["media"] = {"file_name": filename or kind + suffix, "mime_type": mime}
                            else:
                                event["media_unavailable"] = True
                    else:
                        event["media_unavailable"] = True
                elif kind == "contact":
                    event["kind"] = "contact"
                elif kind == "location":
                    event.update(kind="location", location={k: part[k] for k in ("latitude", "longitude") if k in part})
                else:
                    event["kind"] = "unsupported"
                    event["media_unavailable"] = True
            if event["kind"] != "text" or event["text"].strip():
                await gateway.inbound(event)
