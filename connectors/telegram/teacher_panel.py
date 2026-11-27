"""Persistent teacher menu; all data is fetched from the universal Core RPC."""
import asyncio
import json
import logging

from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove

from connectors.common.commands import Commands

logger = logging.getLogger(__name__)
BACK = "К списку учеников"
REFRESH = "↻ Обновить"
PREVIOUS = "← Предыдущая"
NEXT = "Следующая →"


def render(view, page):
    visible, page, total = Commands.page(view["conversations"], page)
    chat = view.get("chat")
    def button(text, action):
        return InlineKeyboardButton(text=text, callback_data="panel:" + action)

    students = [button(item["name"].strip(), f"open:{item['id']}") for item in visible]
    keyboard = [students[i:i + 2] for i in range(0, len(students), 2)]
    nav = ([button(PREVIOUS, "previous")] if page else [])
    if page + 1 < total:
        nav.append(button(NEXT, "next"))
    if nav:
        keyboard.append(nav)
    keyboard.append([button(BACK, "back"), button(REFRESH, "refresh")])
    markup = InlineKeyboardMarkup(inline_keyboard=keyboard)
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
    signature = json.dumps([[[(b.text, b.callback_data) for b in row] for row in keyboard]], ensure_ascii=False)
    return "\n".join(lines)[:3900], markup, page, signature


class TeacherPanel:
    def __init__(self, bot):
        self.bot = bot
        self.locks = {}

    async def refresh(self, actor, gateway, spool, *, page=None, force=False, background=False, view=None):
        lock = self.locks.setdefault(actor, asyncio.Lock())
        async with lock:
            previous = spool.panel(actor)
            commands = Commands(gateway, spool)
            if view is None or commands.selection(actor) is not None:
                view = await commands.panel(actor)
            if (view.get("account") or {}).get("role") != "teacher":
                await self.remove_for_non_teacher(actor, view, spool, previous, background=background)
                return
            if background and not previous.get("message_id"):
                return
            if commands.selection(actor) is not None and not view.get("chat"):
                commands.clear(actor)
            text, markup, page, signature = render(view, previous.get("page", 0) if page is None else page)
            buttons = [button.text for row in markup.inline_keyboard for button in row]
            old_id = previous.get("message_id")
            if old_id and signature == previous.get("signature") and (background or not force):
                if previous.get("text") == text:
                    return
                try:
                    await self.bot.edit_message_text(chat_id=int(actor), message_id=old_id, text=text)
                except TelegramBadRequest as exc:
                    if "message is not modified" not in str(exc).lower():
                        if background:
                            return
                        old_id = None
                if old_id:
                    spool.save_panel(actor, {**previous, "role": "teacher", "buttons": buttons,
                                             "text": text})
                    return
            if background and not previous.get("message_id"):
                return
            if previous.get("message_id") and previous.get("role") in {None, "teacher"} and not previous.get("inline"):
                await self.bot.send_message(int(actor), "Панель учителя обновлена.", reply_markup=ReplyKeyboardRemove())
            sent = await self.bot.send_message(int(actor), text, reply_markup=markup)
            spool.save_panel(actor, {"message_id": sent.message_id, "page": page, "signature": signature,
                                     "text": text, "role": "teacher", "buttons": buttons,
                                     "stale_buttons": previous.get("stale_buttons", []), "inline": True})
            if previous.get("message_id") and previous["message_id"] != sent.message_id:
                try:
                    await self.bot.delete_message(int(actor), previous["message_id"])
                except TelegramAPIError:
                    logger.debug("Previous panel no longer deletable")

    async def remove_for_non_teacher(self, actor, view, spool, previous=None, *, background=False):
        previous = previous or spool.panel(actor)
        was_teacher = previous.get("role") == "teacher" or (
            previous.get("role") is None and previous.get("message_id") is not None
        )
        stale = set(previous.get("stale_buttons", []))
        if was_teacher:
            stale.update(previous.get("buttons", []))
            if not previous.get("buttons"):
                stale.update(self.legacy_buttons(previous.get("text", ""), previous.get("signature")))
        role = (view.get("account") or {}).get("role")
        if background and not was_teacher:
            return
        if role == "student":
            items = view.get("conversations") or []
            text = "Ваш преподаватель: " + items[0]["name"] if items else "Пока нет назначенного преподавателя."
        else:
            text = "Управление доступно в веб-панели."
        sent = await self.bot.send_message(
            int(actor), text, reply_markup=ReplyKeyboardRemove(),
        )
        spool.save_panel(actor, {"message_id": sent.message_id, "role": role, "text": text,
                                 "buttons": [], "stale_buttons": sorted(stale)})

    @staticmethod
    def legacy_buttons(text, signature=None):
        if signature:
            try:
                rows = json.loads(signature)[0]
                return [label for row in rows for label in row if label]
            except (ValueError, TypeError, IndexError):
                pass
        return [line.removeprefix("🔸 ").strip() for line in text.splitlines()
                if line.startswith("🔸 ")]

    @classmethod
    def is_stale_action(cls, actor, text, spool):
        if spool is None:
            return False
        previous = spool.panel(actor)
        buttons = set(previous.get("stale_buttons", []))
        if previous.get("role") == "teacher" or (
            previous.get("role") is None and previous.get("message_id")
        ):
            buttons.update(previous.get("buttons", []))
            if not previous.get("buttons"):
                buttons.update(cls.legacy_buttons(previous.get("text", ""), previous.get("signature")))
        return text.strip() in buttons or text.strip() in {BACK, REFRESH, PREVIOUS, NEXT}

    async def callback(self, callback, gateway, spool):
        actor = str(callback["from"]["id"])
        message = callback.get("message") or {}
        panel = spool.panel(actor)
        data = callback.get("data") or ""
        if (message.get("chat", {}).get("type") != "private"
                or message.get("message_id") != panel.get("message_id")
                or not data.startswith("panel:")):
            await self.bot.answer_callback_query(callback["id"], text="Панель обновилась. Нажмите /start.")
            return
        await self.bot.answer_callback_query(callback["id"])
        commands = Commands(gateway, spool)
        view = await commands.menu(actor)
        page = panel.get("page", 0)
        if (view.get("account") or {}).get("role") == "teacher":
            action = data.removeprefix("panel:")
            if action.startswith("open:"):
                for index, item in enumerate(view["conversations"]):
                    if str(item["id"]) == action[5:]:
                        await commands.open(actor, item["id"])
                        page = index // 6
                        break
            elif action in {"back", "previous", "next"}:
                commands.clear(actor)
                page += {"back": 0, "previous": -1, "next": 1}[action]
        await self.refresh(actor, gateway, spool, page=page)

    async def action(self, actor, message_id, text, view, gateway, spool):
        commands = Commands(gateway, spool)
        body = text.strip()
        page = spool.panel(actor).get("page", 0)
        visible, page, total = commands.page(view["conversations"], page)
        if body.startswith("Написать · "):
            # Старая клавиатура не должна отправить свою подпись как ДЗ.
            await self.refresh(actor, gateway, spool, page=page, force=True)
            return True
        if body in {BACK, REFRESH, PREVIOUS, NEXT}:
            if body != REFRESH:
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
