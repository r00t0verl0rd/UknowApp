"""Public Telegram bot entry point.

Implementation is split into common helpers, teacher UI and update handlers.
The imports below keep the former telegram_bot module API available.
"""

from aiogram import Dispatcher

from .telegram_common import (
    CONNECTION_CODE_RE,
    claim_connection_code,
    contact_would_be_exposed,
    current_student_conversation,
    get_linked_user,
    message_metadata,
    persist_message,
)
from .telegram_handlers import (
    choose_conversation,
    handle_panel_callback,
    open_menu,
    route_message,
    router,
    start,
)
from .telegram_teacher import (
    TEACHER_BACK_LABEL,
    conversation_messages,
    message_preview,
    pending_student_messages,
    TEACHER_KEYBOARD_VERSION,
    TEACHER_NEXT_PAGE_LABEL,
    TEACHER_PAGE_SIZE,
    TEACHER_PREVIOUS_PAGE_LABEL,
    TEACHER_REFRESH_LABEL,
    _teacher_button_labels,
    _teacher_keyboard,
    _teacher_page,
    _update_teacher_panel_locked,
    clear_teacher_session,
    get_teacher_conversation,
    handle_teacher_keyboard_message,
    set_teacher_session,
    teacher_chat_view,
    teacher_conversations,
    teacher_keyboard_actions,
    teacher_keyboard_signature,
    teacher_panel_view,
    update_teacher_panel,
)


def create_dispatcher() -> Dispatcher:
    dispatcher = Dispatcher()
    dispatcher.include_router(router)
    return dispatcher


__all__ = ["create_dispatcher", "router"]
