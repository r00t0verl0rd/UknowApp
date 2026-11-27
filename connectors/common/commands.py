"""Universal chat commands; provider adapters decide how to render views."""
import re
import secrets

CODE = re.compile(r"^[A-HJ-NP-Z2-9]{8}$")


class Commands:
    def __init__(self, gateway, spool):
        self.gateway = gateway
        self.spool = spool

    async def menu(self, actor):
        return await self.gateway.rpc("conversation.list", actor=actor)

    async def bind(self, actor, chat, text, username=None):
        code = re.sub(r"[\s-]", "", text).upper()
        if not CODE.fullmatch(code):
            return None
        return await self.gateway.rpc("account.bind", actor=actor, chat_id=chat, code=code, username=username)

    async def open(self, actor, conversation):
        result = await self.gateway.rpc("conversation.open", actor=actor, conversation_id=conversation)
        self.spool.select_conversation(actor, conversation)
        return result

    def clear(self, actor):
        self.spool.select_conversation(actor, None)

    def selection(self, actor):
        return self.spool.selected_conversation(actor)

    async def panel(self, actor):
        return await self.gateway.rpc("panel.sync", actor=actor, conversation_id=self.selection(actor))

    @staticmethod
    def page(items, page, size=6):
        total = max(1, (len(items) + size - 1) // size)
        page = max(0, min(page, total - 1))
        return items[page * size:(page + 1) * size], page, total


BACK = "К списку учеников"
REFRESH = "↻ Обновить"
PREVIOUS = "← Предыдущая"
NEXT = "Следующая →"
STALE_PANEL = "Панель устарела. Откройте актуальную панель командой /menu."
SELECT_RECIPIENT = "Выберите ученика в актуальной панели и повторите отправку."
AMBIGUOUS_NAME = "У нескольких учеников одинаковое имя. Выберите нужного кнопкой или обратитесь к администратору."


def panel_revision(previous, page, chat, buttons):
    """Reuse the revision only while the displayed navigation and recipient stay the same."""
    state = [page, (chat or {}).get("id"), buttons]
    if previous.get("navigation_state") == state and previous.get("revision"):
        return previous["revision"], state
    return secrets.token_hex(6), state


def callback_action(data, panel):
    revision = panel.get("revision")
    if not revision or not data.startswith(revision + ":"):
        return None
    action = data[len(revision) + 1:]
    return action if action in panel.get("actions", []) else None


def recipient_ready(spool, actor, conversations):
    selection = spool.selected_conversation(actor)
    panel = spool.panel(actor) or {}
    return (selection is not None and panel.get("role") == "teacher"
            and panel.get("recipient") == selection
            and bool(panel.get("revision"))
            and any(c["id"] == selection for c in conversations))


def menu_page(text):
    folded = text.strip().casefold()
    args = folded.split()
    if folded in {"menu", "меню"} or args and args[0] in {"/start", "/menu"}:
        valid = len(args) == 2 and args[0] == "/menu" and args[1].isascii() and args[1].isdecimal() and len(args[1]) <= 5
        return max(0, int(args[1]) - 1) if valid else 0
    return None


async def navigation(commands, actor, text, view, page):
    """Return (page, notice) for recognized teacher commands, else None."""
    body = text.strip()
    folded = body.casefold()
    args = folded.split()
    reset_page = menu_page(body)
    if reset_page is not None:
        commands.clear(actor)
        return reset_page, None
    if folded in {"/back", BACK.casefold()}:
        commands.clear(actor)
        return page, None
    if folded == REFRESH.casefold():
        return page, None
    if folded in {PREVIOUS.casefold(), NEXT.casefold()}:
        commands.clear(actor)
        return page + (1 if folded == NEXT.casefold() else -1), None
    items = view.get("conversations") or []
    if args and args[0] == "/open":
        matches = [i for i in items if len(args) == 2 and str(i["id"]) == args[1]]
        if not matches:
            commands.clear(actor)
            return page, SELECT_RECIPIENT
    else:
        matches = [i for i in items if i["name"].strip() == body]
        if not matches:
            return None
    if len(matches) != 1:
        commands.clear(actor)
        return page, AMBIGUOUS_NAME
    await commands.open(actor, matches[0]["id"])
    return items.index(matches[0]) // 6, None
