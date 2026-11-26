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

from app.infrastructure.storage.conversation_counters import (
    STUDENT_UNREAD,
    TEACHER_UNREAD,
    install_on_create,
)

from .core.database import Base
from .core.runtime_database import RuntimeBase
from .core.security import normalize_login


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
    messenger_accounts: Mapped[list["MessengerAccount"]] = relationship(lazy="select", cascade="all, delete-orphan", passive_deletes=True, back_populates="user")
    web_password_hash: Mapped[str | None] = mapped_column(String(160), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


@event.listens_for(User, "before_insert")
@event.listens_for(User, "before_update")
def _refresh_login_lookup(_mapper, _connection, user: User) -> None:
    # При изменениях синхронизируем индексированный логин.
    user.web_login_key = normalize_login(user.web_username or user.full_name)


class PushSubscription(RuntimeBase):
    __tablename__ = "push_subscriptions"
    __table_args__ = (Index("ix_push_role_state", "role", "delivery_state"),
                      Index("ix_push_session_hash", "session_hash"), {"sqlite_autoincrement": True})

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="teacher")
    endpoint: Mapped[str] = mapped_column(String(2048), unique=True, nullable=False)
    p256dh: Mapped[str] = mapped_column(String(256), nullable=False)
    auth: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    session_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    revision: Mapped[str | None] = mapped_column(String(64), nullable=True)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivery_state: Mapped[str | None] = mapped_column(String(24), nullable=True)
    last_http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)


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

    # Exact business aggregates, maintained transactionally by message triggers.
    message_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default=text("0"))
    teacher_unread_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default=text("0"))
    student_unread_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default=text("0"))
    admin_unread_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default=text("0"))
    last_message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    teacher_last_read_id: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    student_last_read_id: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))

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


class Message(Base):
    __tablename__ = "messages"
    # Ускоряет выборку истории и сортировку сообщений внутри одного диалога.
    __table_args__ = (
        Index("ix_messages_conversation_created_id", "conversation_id", "created_at", "id"),
        Index("ix_messages_conversation_id_id", "conversation_id", "id"),
        Index("ix_messages_teacher_unread", "conversation_id", "id", sqlite_where=text(TEACHER_UNREAD), postgresql_where=text(TEACHER_UNREAD)),
        Index("ix_messages_student_unread", "conversation_id", "id", sqlite_where=text(STUDENT_UNREAD), postgresql_where=text(STUDENT_UNREAD)),
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
    # Authoritative receipt timestamps. JSON contains only other metadata.
    teacher_read_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    student_read_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    client_message_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    delivery_status: Mapped[str] = mapped_column(String(30), default="received", nullable=False)
    source_platform: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source_event_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    sender: Mapped[User] = relationship()


class MessageIdCounter(Base):
    """Durable SQLite high-water marks; normal message IDs must never be reused."""
    __tablename__ = "message_id_counters"

    table_name: Mapped[str] = mapped_column(String(32), primary_key=True)
    last_id: Mapped[int] = mapped_column(BigInteger, nullable=False)


@event.listens_for(Message, "before_insert")
@event.listens_for(PersonalMessage, "before_insert")
def _allocate_message_id(mapper, connection, message):
    if connection.dialect.name != "sqlite":
        return
    table = mapper.local_table
    # Fixed ORM table names only. The first allocation skips legacy IDs that
    # might still be held by an older client, including recently deleted rows.
    if table.name == "messages":
        source = "messages"
    elif table.name == "personal_messages":
        source = "personal_messages"
    else:
        raise ValueError("Unknown message table")
    if message.id is not None:
        connection.execute(text("""
            INSERT INTO message_id_counters (table_name, last_id)
            VALUES (:table_name, :message_id)
            ON CONFLICT (table_name) DO UPDATE SET last_id = max(last_id, excluded.last_id)
        """), {"table_name": source, "message_id": message.id})
        return
    message.id = connection.scalar(text(f"""
        INSERT INTO message_id_counters (table_name, last_id)
        SELECT :table_name, max(1000000000, coalesce(max(id), 0) + 1)
        FROM {source} WHERE true
        ON CONFLICT (table_name) DO UPDATE SET last_id = max(last_id + 1, excluded.last_id)
        RETURNING last_id
    """), {"table_name": source})


class ConnectionCode(Base):
    __tablename__ = "connection_codes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    code_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship()




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

    user: Mapped[User] = relationship(back_populates="messenger_accounts")


class BotEventReceipt(Base):
    """Receipt for a completed connector event; survives Core restart."""

    __tablename__ = "bot_event_receipts"

    platform: Mapped[str] = mapped_column(String(32), primary_key=True)
    event_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)



class ExternalEndpoint(Base):
    """An optional conversation endpoint for an account, independent of provider."""
    __tablename__ = "external_endpoints"
    __table_args__ = (UniqueConstraint("platform", "chat_id", "thread_id"),)

    platform: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    chat_id: Mapped[str] = mapped_column(String(255), nullable=False)
    thread_id: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    preferred: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class ConnectorDelivery(Base):
    """Durable business delivery intent and claim fence; transport state lives in Runtime DB."""
    __tablename__ = "connector_deliveries"
    __table_args__ = (UniqueConstraint("message_id", "platform", "recipient_id", "chat_id", "thread_id", name="uq_connector_delivery_route"),
                      Index("ix_connector_delivery_queue", "platform", "status", "created_at", "id"),
                      Index("ix_connector_delivery_route_order", "platform", "chat_id", "thread_id", "status", "created_at", "id"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    message_id: Mapped[int | None] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"), index=True, nullable=True)
    recipient_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    platform: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    external_user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    chat_id: Mapped[str] = mapped_column(String(255), nullable=False)
    thread_id: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued", index=True)
    external_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    claim_id: Mapped[str | None] = mapped_column(String(64), nullable=True)


class ConnectorDeletion(Base):
    """Durable external-copy deletion, independent of the deleted message row."""
    __tablename__ = "connector_deletions"
    __table_args__ = (Index("ix_connector_deletion_queue", "platform", "status", "created_at", "id"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    platform: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    chat_id: Mapped[str] = mapped_column(String(255), nullable=False)
    external_message_id: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    claim_id: Mapped[str | None] = mapped_column(String(64), nullable=True)


class TransportJob(RuntimeBase):
    """Operational publication state, reconstructible from durable business intents."""
    __tablename__ = "transport_jobs"
    __table_args__ = (Index("ix_transport_jobs_pending", "platform", "state", "published_at"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    chat_id: Mapped[str] = mapped_column(String(255), nullable=False)
    thread_id: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    heavy: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    broker_seq: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


# Also install on fresh/test schemas created directly via metadata.create_all.
event.listen(Message.__table__, "after_create", install_on_create)
