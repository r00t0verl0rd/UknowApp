 # Frozen historical model snapshot; test-only, source 15d2ea8fdad244526300d9900f7fee9160ce6205
"""Модели таблиц базы данных и связи между сущностями UknowApp."""

from datetime import UTC, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from sqlalchemy.orm import DeclarativeBase

class Base(DeclarativeBase):
    pass

from app.core.security import normalize_login


def utcnow() -> datetime:
    return datetime.now(UTC)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    full_name: Mapped[str] = mapped_column(String(160), nullable=False)
    additional_info: Mapped[str | None] = mapped_column(String(500), nullable=True)
    web_username: Mapped[str | None] = mapped_column(String(160), nullable=True)
    web_login_key: Mapped[str | None] = mapped_column(String(320), nullable=True, index=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    telegram_id: Mapped[int | None] = mapped_column(BigInteger, unique=True, nullable=True, index=True)
    web_password_hash: Mapped[str | None] = mapped_column(String(160), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


@event.listens_for(User, "before_insert")
@event.listens_for(User, "before_update")
def _refresh_login_lookup(_mapper, _connection, user: User) -> None:
    # При изменениях синхронизируем индексированный логин.
    user.web_login_key = normalize_login(user.web_username or user.full_name)


class PushSubscription(Base):
    __tablename__ = "push_subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="teacher")
    endpoint: Mapped[str] = mapped_column(String(2048), unique=True, nullable=False)
    p256dh: Mapped[str] = mapped_column(String(256), nullable=False)
    auth: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class PanelSession(Base):
    __tablename__ = "panel_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    credential_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)


class Assignment(Base):
    __tablename__ = "assignments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    teacher_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    teacher: Mapped[User] = relationship(foreign_keys=[teacher_id])
    student: Mapped[User] = relationship(foreign_keys=[student_id])
    conversation: Mapped["Conversation"] = relationship(back_populates="assignment", uselist=False)


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    assignment_id: Mapped[int | None] = mapped_column(ForeignKey("assignments.id"), unique=True, nullable=True)
    teacher_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    assignment: Mapped[Assignment | None] = relationship(back_populates="conversation")
    teacher: Mapped[User] = relationship(foreign_keys=[teacher_id])
    student: Mapped[User] = relationship(foreign_keys=[student_id])


class PersonalConversation(Base):
    __tablename__ = "personal_conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    participant_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    participant: Mapped[User] = relationship()


class PersonalChatCounter(Base):
    __tablename__ = "personal_chat_counter"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    last_id: Mapped[int] = mapped_column(Integer, nullable=False)


@event.listens_for(PersonalConversation, "before_insert")
def _allocate_personal_id(_mapper, connection, chat):
    if connection.dialect.name != "sqlite" or chat.id is not None:
        return
    # Existing SQLite tables lack AUTOINCREMENT. Keep a durable high-water mark
    # and start the new range above legacy IDs, including recently deleted ones.
    chat.id = connection.scalar(text("""
        INSERT INTO personal_chat_counter (id, last_id)
        SELECT 1, max(1000000000, coalesce(max(id), 0) + 1)
        FROM personal_conversations WHERE true
        ON CONFLICT (id) DO UPDATE SET last_id = max(last_id + 1, excluded.last_id)
        RETURNING last_id
    """))


class PersonalMediaCleanup(Base):
    __tablename__ = "personal_media_cleanup"

    conversation_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)


class PersonalMessage(Base):
    __tablename__ = "personal_messages"
    __table_args__ = (
        Index("ix_personal_messages_conversation_created_id", "conversation_id", "created_at", "id"),
        Index("ix_personal_messages_conversation_id_id", "conversation_id", "id"),
        Index(
            "uq_personal_messages_client_message_id",
            "conversation_id",
            "sender_role",
            "client_message_id",
            unique=True,
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("personal_conversations.id"), nullable=False)
    sender_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    sender_role: Mapped[str] = mapped_column(String(20), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    client_message_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    admin_read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    participant_read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    sender: Mapped[User | None] = relationship()

class TeacherSession(Base):
    __tablename__ = "teacher_sessions"

    teacher_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Message(Base):
    __tablename__ = "messages"
    # Ускоряет выборку истории и сортировку сообщений внутри одного диалога.
    __table_args__ = (
        Index("ix_messages_conversation_created_id", "conversation_id", "created_at", "id"),
        Index("ix_messages_conversation_id_id", "conversation_id", "id"),
        Index(
            "uq_messages_client_message_id",
            "conversation_id",
            "sender_id",
            "client_message_id",
            unique=True,
        ),
        Index(
            "uq_messages_inbound_event",
            "sender_id",
            "source_platform",
            "source_event_id",
            unique=True,
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"), nullable=False)
    sender_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    sender_role: Mapped[str] = mapped_column(String(20), nullable=False)
    content_type: Mapped[str] = mapped_column(String(40), default="text", nullable=False)
    text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    client_message_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    delivery_status: Mapped[str] = mapped_column(String(30), default="received", nullable=False)
    source_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    source_platform: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source_event_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    destination_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    sender: Mapped[User] = relationship()


class ConnectionCode(Base):
    __tablename__ = "connection_codes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    code_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship()


class TeacherPanel(Base):
    __tablename__ = "teacher_panels"

    teacher_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    keyboard_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    keyboard_signature: Mapped[str | None] = mapped_column(String(64), nullable=True)
    page_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class StudentTelegramGroup(Base):
    """Тема Telegram, привязанная к переписке ученика."""

    __tablename__ = "student_telegram_groups"
    __table_args__ = (
        UniqueConstraint("chat_id", "thread_id", name="uq_student_telegram_group_topic"),
    )

    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    thread_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    group_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    bound_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    student: Mapped[User] = relationship()



class MessengerAccount(Base):
    """Аккаунт мессенджера, привязанный к пользователю."""

    __tablename__ = "messenger_accounts"
    __table_args__ = (
        UniqueConstraint(
            "platform",
            "external_user_id",
            name="uq_messenger_accounts_platform_external_user",
        ),
        UniqueConstraint(
            "platform",
            "user_id",
            name="uq_messenger_accounts_platform_user",
        ),
        Index("ix_messenger_accounts_user_id", "user_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    external_user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    external_chat_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="linked")
    linked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=utcnow,
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    user: Mapped[User] = relationship()


class RealtimeEvent(Base):
    """Журнал событий сообщений и прочтения."""

    __tablename__ = "realtime_events"
    __table_args__ = (
        Index("ix_realtime_events_created_at", "created_at"),
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    conversation_type: Mapped[str] = mapped_column(String(20), nullable=False, default="conversation")
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class BotEventReceipt(Base):
    """Receipt for a completed connector event; survives Core restart."""

    __tablename__ = "bot_event_receipts"

    platform: Mapped[str] = mapped_column(String(32), primary_key=True)
    event_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class BotDeliveryJob(Base):
    """Durable web-to-messenger outbox. Unknown outcomes are never blindly retried."""

    __tablename__ = "bot_delivery_jobs"

    message_id: Mapped[int] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), primary_key=True,
    )
    status: Mapped[str] = mapped_column(String(20), default="queued", nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
