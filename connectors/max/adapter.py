"""Local MAX Bot API adapter for private school conversations."""
import asyncio
from urllib.parse import urlsplit

import aiohttp

from connectors.common.client import DeliveryRejected, RetryLater
from connectors.common.commands import CODE, Commands

API = "https://platform-api2.max.ru"
KINDS = {"image": "photo", "video": "video", "audio": "audio", "file": "document"}
BACK = "К списку учеников"
REFRESH = "↻ Обновить"
PREVIOUS = "← Предыдущая"
NEXT = "Следующая →"


class MaxAdapter:
    def __init__(self, http, token):
        self.http = http
        self.headers = {"Authorization": token}

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
            kind = {"photo": "image", "voice": "audio", "animation": "video"}.get(job["kind"], job["kind"])
            if kind not in KINDS:
                kind = "file"
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
        text = job.get("text") or ""
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
        message = update.get("message") or {}
        sender = message.get("sender") or update.get("user") or {}
        return str(sender.get("user_id", "")), bool(message.get("body", {}).get("attachments"))

    async def refresh_panel(self, actor, gateway, spool, background=False, page=None):
        commands = Commands(gateway, spool)
        result = await commands.panel(actor)
        chat = result.get("chat")
        previous = spool.panel(actor) or {}
        page = previous.get("page", 0) if page is None else page
        visible, page, total = commands.page(result["conversations"], page)
        buttons = [[item["name"].strip() for item in visible[i:i + 2]]
                   for i in range(0, len(visible), 2)]
        navigation = ([PREVIOUS] if page else []) + ([NEXT] if page + 1 < total else [])
        if navigation:
            buttons.append(navigation)
        buttons.append([BACK, REFRESH])
        if chat:
            lines = [chat["name"], *(m["name"] + ": " + (m["text"] or m["preview"]) for m in chat["messages"])]
        else:
            lines = [f"Ваша группа · страница {page + 1}/{total}"]
            for item in visible:
                lines.append(item["name"] + (f" · {item['unread']} новых" if item["unread"] else ""))
                lines.append(item["last_message"] or "")
        text = "\n".join(lines)
        text = text if len(text) <= 4000 else text[:160] + "\n…\n" + text[-3830:]
        keyboard = [{"type": "inline_keyboard", "payload": {"buttons": [
            [{"type": "message", "text": label} for label in row] for row in buttons
        ]}}] if buttons else []
        if previous.get("mid"):
            if background and previous.get("text") == text:
                return
            try:
                await self.api("PUT", "/messages", params={"message_id": previous["mid"]}, body={"text": text, "attachments": keyboard})
                spool.save_panel(actor, {"mid": previous["mid"], "text": text, "page": page})
                return
            except DeliveryRejected:
                pass
        if not background or previous:
            mid = await self.message(actor, text, keyboard)
            spool.save_panel(actor, {"mid": mid, "text": text, "page": page})

    async def handle(self, event_id, update, gateway, spool):
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
        if not account["account"]:
            bound = await commands.bind(actor, actor, text)
            if not bound or not bound.get("account"):
                await self.message(actor, "Для подключения отправьте действующий код входа в школу.")
                return
            await self.show_account(actor, bound, gateway, spool)
            return
        if CODE.fullmatch(text.replace("-", "").replace(" ", "").upper()):
            await self.show_account(actor, account, gateway, spool)
            return
        folded = text.casefold()
        page_arg = text[6:].strip() if folded.startswith("/menu ") else ""
        numbered_menu = bool(page_arg and page_arg.isascii() and page_arg.isdecimal() and len(page_arg) <= 5)
        page = (int(page_arg) - 1) if numbered_menu else None
        if folded in {"/menu", "menu", "меню", "/start", "/back", BACK.casefold()} or numbered_menu:
            commands.clear(actor)
            await self.refresh_panel(actor, gateway, spool, page=page or 0)
            return
        if folded == REFRESH.casefold():
            await self.refresh_panel(actor, gateway, spool)
            return
        if folded in {PREVIOUS.casefold(), NEXT.casefold()}:
            current = (spool.panel(actor) or {}).get("page", 0)
            commands.clear(actor)
            await self.refresh_panel(actor, gateway, spool,
                                     page=current + (1 if folded == NEXT.casefold() else -1))
            return
        if text.startswith("/open "):
            ident = text[6:].strip()
            if ident.isdecimal() and any(str(c["id"]) == ident for c in account["conversations"]):
                await commands.open(actor, int(ident))
            await self.refresh_panel(actor, gateway, spool)
            return
        matches = [c for c in account["conversations"] if c["name"].strip() == text]
        if len(matches) == 1:
            await commands.open(actor, matches[0]["id"])
            index = next(i for i, c in enumerate(account["conversations"]) if c["id"] == matches[0]["id"])
            await self.refresh_panel(actor, gateway, spool, page=index // 6)
            return
        if len(matches) > 1:
            await self.message(actor, "У нескольких учеников одинаковое имя. Попросите администратора различить их.")
            return
        selection = commands.selection(actor)
        if account["account"]["role"] == "teacher" and selection not in [c["id"] for c in account["conversations"]]:
            await self.refresh_panel(actor, gateway, spool)
            return
        await self.forward_parts(event_id, actor, actor, "private", selection, body, gateway)

    async def show_account(self, actor, account, gateway, spool):
        role = account["account"]["role"]
        if role == "teacher":
            await self.refresh_panel(actor, gateway, spool)
        elif role == "student":
            items = account["conversations"]
            text = "Ваш преподаватель: " + items[0]["name"] if items else "Пока нет назначенного преподавателя."
            await self.message(actor, text)
        else:
            await self.message(actor, "Управление доступно в веб-панели.")

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
                    event["kind"] = KINDS[kind]
                    payload = part.get("payload") or {}
                    url = payload.get("url") or ""
                    host = urlsplit(url).hostname or ""
                    trusted = any(host == domain or host.endswith("." + domain)
                                  for domain in ("max.ru", "okcdn.ru", "mycdn.me", "usercontent.max.ru", "vkuser.net"))
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
                                    event["media"] = {"file_name": part.get("filename") or kind,
                                                      "mime_type": source.content_type}
                            else:
                                event["media_unavailable"] = True
                    else:
                        event["media_unavailable"] = True
                elif kind == "contact":
                    event["kind"] = "contact"
                elif kind == "location":
                    event.update(kind="location", location={k: part[k] for k in ("latitude", "longitude") if k in part})
                elif not event["text"]:
                    await self.message(actor, "Этот тип вложения пока не поддерживается. Отправьте его файлом.")
                    continue
            if event["kind"] != "text" or event["text"].strip():
                await gateway.inbound(event)
