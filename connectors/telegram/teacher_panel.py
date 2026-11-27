"""Persistent teacher menu; all data is fetched from the universal Core RPC."""
import asyncio
import json
import logging

from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove

from connectors.common.commands import (
    Commands, BACK, REFRESH, PREVIOUS, NEXT, STALE_PANEL,
    panel_revision, callback_action, navigation,
)
from connectors.common.panel_text import teacher_panel_text

logger = logging.getLogger(__name__)


def render(view, page, previous=None):
    visible, page, total = Commands.page(view["conversations"], page)
    actions = [f"open:{item['id']}" for item in visible]
    actions += (["previous"] if page else []) + (["next"] if page + 1 < total else []) + ["back", "refresh"]
    revision, state = panel_revision(previous or {}, page, view.get("chat"), actions)
    def button(text, action):
        return InlineKeyboardButton(text=text, callback_data="panel:" + revision + ":" + action)

    students = [button(item["name"].strip(), f"open:{item['id']}") for item in visible]
    keyboard = [students[i:i + 2] for i in range(0, len(students), 2)]
    nav = ([button(PREVIOUS, "previous")] if page else [])
    if page + 1 < total:
        nav.append(button(NEXT, "next"))
    if nav:
        keyboard.append(nav)
    keyboard.append([button(BACK, "back"), button(REFRESH, "refresh")])
    markup = InlineKeyboardMarkup(inline_keyboard=keyboard)
    signature = json.dumps([[[(b.text, b.callback_data) for b in row] for row in keyboard]], ensure_ascii=False)
    return teacher_panel_text(view.get("chat"), visible, page, total), markup, page, signature


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
            requested = previous.get("page", 0) if page is None else page
            visible, page, total = Commands.page(view["conversations"], requested)
            actions = [f"open:{item['id']}" for item in visible]
            actions += (["previous"] if page else []) + (["next"] if page + 1 < total else []) + ["back", "refresh"]
            revision, state = panel_revision(previous, page, view.get("chat"), actions)
            panel_state = {"revision": revision, "navigation_state": state, "actions": actions,
                           "recipient": (view.get("chat") or {}).get("id")}
            text, markup, page, signature = render(view, page, panel_state)
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
                    spool.save_panel(actor, {**previous, **panel_state, "role": "teacher", "buttons": buttons,
                                             "text": text})
                    return
            if background and not previous.get("message_id"):
                return
            if previous.get("message_id") and previous.get("role") in {None, "teacher"} and not previous.get("inline"):
                await self.bot.send_message(int(actor), "Панель учителя обновлена.", reply_markup=ReplyKeyboardRemove())
            sent = await self.bot.send_message(int(actor), text, reply_markup=markup)
            spool.save_panel(actor, {**panel_state, "message_id": sent.message_id, "page": page, "signature": signature,
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
        action = callback_action(data.removeprefix("panel:"), panel) if data.startswith("panel:") else None
        if (message.get("chat", {}).get("type") != "private"
                or not panel.get("message_id") or message.get("message_id") != panel.get("message_id")
                or not action):
            await self.bot.answer_callback_query(callback["id"], text=STALE_PANEL)
            return
        commands = Commands(gateway, spool)
        view = await commands.menu(actor)
        if spool.panel(actor).get("revision") != panel.get("revision"):
            await self.bot.answer_callback_query(callback["id"], text=STALE_PANEL)
            return
        await self.bot.answer_callback_query(callback["id"])
        page = panel.get("page", 0)
        if (view.get("account") or {}).get("role") == "teacher":
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
        if body.startswith("Написать · "):
            await self.refresh(actor, gateway, spool, page=page, force=True)
            return True
        action = await navigation(commands, actor, body, view, page)
        if action is None:
            if not self.is_stale_action(actor, body, spool):
                return False
            await self.bot.send_message(int(actor), STALE_PANEL)
        else:
            page, notice = action
            if notice:
                await self.bot.send_message(int(actor), notice)
        try:
            await self.bot.delete_message(int(actor), message_id)
        except TelegramAPIError:
            pass
        await self.refresh(actor, gateway, spool, page=page)
        return True
