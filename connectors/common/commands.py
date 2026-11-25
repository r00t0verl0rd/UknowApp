"""Universal chat commands; provider adapters decide how to render views."""
import re

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
