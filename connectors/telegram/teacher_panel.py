"""Persistent teacher menu; all data is fetched from the universal Core RPC."""
import asyncio
import json
import logging

from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

from connectors.common.commands import Commands

logger = logging.getLogger(__name__)
BACK = "К списку учеников"
REFRESH = "↻ Обновить"
PREVIOUS = "← Предыдущая"
NEXT = "Следующая →"


def render(view, page):
    visible, page, total = Commands.page(view["conversations"], page)
    chat = view.get("chat")
    labels = [i["name"].strip() for i in visible]
    keyboard = [[KeyboardButton(text=label) for label in labels[i:i+2]] for i in range(0, len(labels), 2)]
    nav = ([KeyboardButton(text=PREVIOUS)] if page else []) + ([KeyboardButton(text=NEXT)] if page + 1 < total else [])
    if nav:
        keyboard.append(nav)
    keyboard.append([KeyboardButton(text=BACK), KeyboardButton(text=REFRESH)])
    placeholder = ("Написать " + chat["name"] if chat else "Сперва выберите ученика")[:64]
    markup = ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True, is_persistent=True,
                                 one_time_keyboard=False, input_field_placeholder=placeholder)
    if chat:
        lines = ["🔸 " + chat["name"]]
        if chat["total"] > len(chat["messages"]):
            lines.append(f'Показаны последние {len(chat["messages"])} из {chat["total"]} сообщений.')
        lines.extend(m["name"] + ": " + m["preview"] for m in chat["messages"])
        if not chat["messages"]:
            lines.append("История пока пуста.")
    else:
        lines = ["▫️ Ваша группа:", ""]
        for item in visible:
            lines.append("🔸 " + item["name"] + (f' · {item["unread"]} новых' if item["unread"] else ""))
            previews = item.get("unread_previews") or []
            lines.extend("   " + p for p in previews or [item["last_message"]])
            if item["unread"] > len(previews) and previews:
                lines.append(f'   …ещё {item["unread"] - len(previews)} сообщений')
            lines.append("")
        if not visible:
            lines.append("Пока нет назначенных учеников.")
        if total > 1:
            lines.append(f"Страница {page+1} из {total}.")
    signature = json.dumps([[[b.text for b in r] for r in keyboard], placeholder], ensure_ascii=False)
    return "\n".join(lines)[:3900], markup, page, signature


class TeacherPanel:
    def __init__(self, bot):
        self.bot = bot
        self.locks = {}

    async def refresh(self, actor, gateway, spool, *, page=None, force=False, background=False, view=None):
        lock = self.locks.setdefault(actor, asyncio.Lock())
        async with lock:
            previous = spool.panel(actor)
            if background and not previous.get("message_id"):
                return
            commands = Commands(gateway, spool)
            if view is None or commands.selection(actor) is not None:
                view = await commands.panel(actor)
            if (view.get("account") or {}).get("role") != "teacher":
                return
            if commands.selection(actor) is not None and not view.get("chat"):
                commands.clear(actor)
            text, markup, page, signature = render(view, previous.get("page", 0) if page is None else page)
            old_id = previous.get("message_id")
            if old_id and (background or not force and signature == previous.get("signature")):
                if previous.get("text") == text:
                    return
                try:
                    await self.bot.edit_message_text(chat_id=int(actor), message_id=old_id, text=text)
                except TelegramBadRequest as exc:
                    if "message is not modified" not in str(exc).lower():
                        if background:
                            return
                        old_id = None
                else:
                    spool.save_panel(actor, {**previous, "text": text})
                    return
                if old_id:
                    spool.save_panel(actor, {**previous, "text": text})
                    return
            if background:
                return
            sent = await self.bot.send_message(int(actor), text, reply_markup=markup)
            spool.save_panel(actor, {"message_id": sent.message_id, "page": page, "signature": signature, "text": text})
            if previous.get("message_id") and previous["message_id"] != sent.message_id:
                try:
                    await self.bot.delete_message(int(actor), previous["message_id"])
                except TelegramAPIError:
                    logger.debug("Previous panel no longer deletable")

    async def action(self, actor, message_id, text, view, gateway, spool):
        commands = Commands(gateway, spool)
        body = text.strip()
        page = spool.panel(actor).get("page", 0)
        visible, page, total = commands.page(view["conversations"], page)
        if body in {BACK, REFRESH, PREVIOUS, NEXT} or body.startswith("Написать · "):
            if body != REFRESH and not body.startswith("Написать · "):
                commands.clear(actor)
            page += 1 if body == NEXT else -1 if body == PREVIOUS else 0
        else:
            matches = [i for i in visible if i["name"].strip() == body]
            if not matches and not any(i["name"].strip() == body for i in view["conversations"]):
                return False
            if len(matches) == 1:
                await commands.open(actor, matches[0]["id"])
            elif len(matches) > 1:
                await self.bot.send_message(int(actor), "У нескольких учеников одинаковое ФИО. Попросите администратора различить их.")
        try:
            await self.bot.delete_message(int(actor), message_id)
        except TelegramAPIError:
            pass
        await self.refresh(actor, gateway, spool, page=page)
        return True
