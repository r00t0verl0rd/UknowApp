"""Transactional personal-chat summaries, including bulk writes and rollback."""
from sqlalchemy import inspect, text

PERSONAL_ADMIN_UNREAD = "sender_role != 'admin' AND admin_read_at IS NULL"
PERSONAL_PARTICIPANT_UNREAD = "sender_role = 'admin' AND participant_read_at IS NULL"


def personal_unread_condition(role):
    return text(PERSONAL_ADMIN_UNREAD if role == "admin" else PERSONAL_PARTICIPANT_UNREAD)


def upgrade_personal_unread_indexes(connection):
    # Условия совпадают с выборками непрочитанных и квитанций.
    connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_personal_admin_unread "
                               "ON personal_messages (conversation_id, id) WHERE " + PERSONAL_ADMIN_UNREAD)
    connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_personal_participant_unread "
                               "ON personal_messages (conversation_id, id) WHERE " + PERSONAL_PARTICIPANT_UNREAD)


def install_personal_triggers(connection):
    # Имена и SQL-выражения заданы внутри приложения.
    execute = connection.exec_driver_sql
    latest = "SELECT created_at FROM personal_messages WHERE conversation_id = {ref}.conversation_id ORDER BY created_at DESC, id DESC LIMIT 1"  # nosec B608

    def unread(ref):
        return (
            f"CASE WHEN {ref}.sender_role <> 'admin' AND {ref}.admin_read_at IS NULL THEN 1 ELSE 0 END",
            f"CASE WHEN {ref}.sender_role = 'admin' AND {ref}.participant_read_at IS NULL THEN 1 ELSE 0 END",
        )

    def update(ref, delta):
        # ref и delta строятся только из констант ниже.
        return ("UPDATE personal_conversations SET " + delta +  # nosec B608
                ", last_message_at = (" + latest.format(ref=ref) + ")" +
                f" WHERE id = {ref}.conversation_id")

    new, old = unread("NEW"), unread("OLD")
    names = ("admin_unread_count", "participant_unread_count")
    add = update("NEW", ", ".join(f"{n} = {n} + ({v})" for n, v in zip(names, new)))
    remove = update("OLD", ", ".join(f"{n} = {n} - ({v})" for n, v in zip(names, old)))
    change = update("NEW", ", ".join(f"{n} = {n} + ({a}) - ({b})" for n, a, b in zip(names, new, old)))
    moved = "OLD.conversation_id <> NEW.conversation_id"
    changed = " OR ".join([*(f"({a}) <> ({b})" for a, b in zip(new, old)),
                           "OLD.created_at <> NEW.created_at", "OLD.id <> NEW.id"])
    fields = "sender_role, admin_read_at, participant_read_at, created_at, id, conversation_id"
    if connection.dialect.name == "sqlite":
        for name in ("insert", "delete", "update", "move"):
            execute(f"DROP TRIGGER IF EXISTS uknow_personal_stats_{name}")
        execute(f"CREATE TRIGGER uknow_personal_stats_insert AFTER INSERT ON personal_messages BEGIN {add}; END")
        execute(f"CREATE TRIGGER uknow_personal_stats_delete AFTER DELETE ON personal_messages BEGIN {remove}; END")
        execute(f"""CREATE TRIGGER uknow_personal_stats_update AFTER UPDATE OF {fields} ON personal_messages
            WHEN NOT ({moved}) AND ({changed}) BEGIN {change}; END""")
        execute(f"""CREATE TRIGGER uknow_personal_stats_move AFTER UPDATE OF conversation_id ON personal_messages
            WHEN {moved} BEGIN {remove}; {add}; END""")
    elif connection.dialect.name == "postgresql":
        execute(f"""CREATE OR REPLACE FUNCTION uknow_personal_stats() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
                IF TG_OP = 'INSERT' THEN
                    PERFORM id FROM personal_conversations WHERE id = NEW.conversation_id FOR NO KEY UPDATE;
                    {add};
                ELSIF TG_OP = 'DELETE' THEN
                    PERFORM id FROM personal_conversations WHERE id = OLD.conversation_id FOR NO KEY UPDATE;
                    {remove};
                ELSIF {moved} THEN
                    PERFORM id FROM personal_conversations WHERE id IN (OLD.conversation_id, NEW.conversation_id)
                        ORDER BY id FOR NO KEY UPDATE;
                    {remove}; {add};
                ELSIF {changed} THEN
                    PERFORM id FROM personal_conversations WHERE id = NEW.conversation_id FOR NO KEY UPDATE;
                    {change};
                END IF;
                RETURN NULL;
            END; $$""")
        execute("DROP TRIGGER IF EXISTS uknow_personal_stats ON personal_messages")
        execute(f"""CREATE TRIGGER uknow_personal_stats AFTER INSERT OR DELETE OR UPDATE OF {fields}
            ON personal_messages FOR EACH ROW EXECUTE FUNCTION uknow_personal_stats()""")
    else:
        raise RuntimeError("Unsupported personal counter dialect")


def install_personal_on_create(_table, connection, **_kwargs):
    if "admin_unread_count" in {c["name"] for c in inspect(connection).get_columns("personal_conversations")}:
        install_personal_triggers(connection)


def upgrade_personal_counters(connection):
    columns = {c["name"] for c in inspect(connection).get_columns("personal_conversations")}
    execute = connection.exec_driver_sql
    for name in ("admin_unread_count", "participant_unread_count"):
        if name not in columns:
            execute(f"ALTER TABLE personal_conversations ADD COLUMN {name} BIGINT NOT NULL DEFAULT 0")
    if "last_message_at" not in columns:
        timestamp = "TIMESTAMP WITH TIME ZONE" if connection.dialect.name == "postgresql" else "DATETIME"
        execute(f"ALTER TABLE personal_conversations ADD COLUMN last_message_at {timestamp}")
    execute("CREATE INDEX IF NOT EXISTS ix_personal_messages_conversation_created_id ON personal_messages (conversation_id, created_at, id)")
    # Групповое заполнение выполняется только при миграции.
    execute("UPDATE personal_conversations SET admin_unread_count=0, participant_unread_count=0, last_message_at=NULL")
    execute("""UPDATE personal_conversations SET admin_unread_count=stats.admin_count,
        participant_unread_count=stats.participant_count, last_message_at=stats.latest
        FROM (SELECT conversation_id,
            SUM(CASE WHEN sender_role <> 'admin' AND admin_read_at IS NULL THEN 1 ELSE 0 END) AS admin_count,
            SUM(CASE WHEN sender_role = 'admin' AND participant_read_at IS NULL THEN 1 ELSE 0 END) AS participant_count,
            MAX(created_at) AS latest FROM personal_messages GROUP BY conversation_id) AS stats
        WHERE personal_conversations.id=stats.conversation_id""")
    install_personal_triggers(connection)
