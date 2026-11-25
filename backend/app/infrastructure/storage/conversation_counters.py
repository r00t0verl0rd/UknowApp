"""Transactional, exact conversation summaries without history scans on reads.

Keep per-message receipts (visible-window reads may leave holes). SQL triggers
cover ORM, bulk SQL, imports and rollback. No process cache can become stale.
"""
import json

from sqlalchemy import inspect, text, Text
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.expression import ColumnElement

COUNTERS = ("teacher_unread_count", "student_unread_count", "admin_unread_count")
TEACHER_UNREAD = "sender_role IN ('student','admin') AND teacher_read_at IS NULL"
STUDENT_UNREAD = "sender_role IN ('teacher','admin') AND student_read_at IS NULL"


class ReadField(ColumnElement):
    type = Text()
    inherit_cache = False

    def __init__(self, name):
        if name not in {"teacher_read_at", "student_read_at"}:
            raise ValueError("Unknown read field")
        self.name = name


def field_sql(name, dialect):
    if dialect == "sqlite":
        return f"CASE WHEN json_valid(metadata_json) THEN json_extract(metadata_json, '$.{name}') ELSE NULL END"
    return f"uknow_read_field(metadata_json, '{name}')"


@compiles(ReadField, "sqlite")
def compile_sqlite(element, compiler, **kwargs):
    return field_sql(element.name, "sqlite")


@compiles(ReadField, "postgresql")
def compile_postgresql(element, compiler, **kwargs):
    return field_sql(element.name, "postgresql")


def install_read_function(connection):
    if connection.dialect.name == "postgresql":
        connection.exec_driver_sql("""CREATE OR REPLACE FUNCTION uknow_read_field(value text, field text)
            RETURNS text LANGUAGE plpgsql IMMUTABLE AS $$
            BEGIN RETURN value::jsonb ->> field;
            EXCEPTION WHEN invalid_text_representation THEN RETURN NULL;
            END; $$""")


def install_read_function_on_create(_table, connection, **_kwargs):
    install_read_function(connection)


def unread_expressions(prefix, dialect):
    role = prefix + "sender_role"
    teacher = f"({role} IN ('student','admin') AND {prefix}teacher_read_at IS NULL)"
    student = f"({role} IN ('teacher','admin') AND {prefix}student_read_at IS NULL)"
    admin = f"({role} IN ('teacher','student') AND ({teacher} OR {student}))"
    return [f"CASE WHEN {condition} THEN 1 ELSE 0 END" for condition in (teacher, student, admin)]


def cursor_assignments(conversation):
    # Greatest existing ID in the contiguous read prefix. Own messages do not
    # count as unread; sparse receipts beyond the prefix remain intact.
    parts = []
    for role, predicate in (("teacher", TEACHER_UNREAD), ("student", STUDENT_UNREAD)):
        first_unread = (f"SELECT id FROM messages WHERE conversation_id = {conversation} "
                        f"AND {predicate} ORDER BY id LIMIT 1")
        prefix = (f"SELECT id FROM messages WHERE conversation_id = {conversation} "
                  f"AND id < COALESCE(({first_unread}), 9223372036854775807) "
                  "ORDER BY id DESC LIMIT 1")
        parts.append(f"{role}_last_read_id = COALESCE(({prefix}), 0)")
    return ", ".join(parts)


def latest_id(conversation):
    return ("(SELECT id FROM messages WHERE conversation_id = " + conversation +
            " ORDER BY created_at DESC, id DESC LIMIT 1)")


def install_triggers(connection):
    dialect = connection.dialect.name
    generated = any(col.get("computed") for col in inspect(connection).get_columns("messages")
                    if col["name"] in {"teacher_read_at", "student_read_at"})
    receipt_fields = "metadata_json" if generated else "teacher_read_at, student_read_at"
    new = unread_expressions("NEW.", dialect)
    old = unread_expressions("OLD.", dialect)
    add = ", ".join(f"{name} = {name} + ({expr})" for name, expr in zip(COUNTERS, new))
    subtract = ", ".join(f"{name} = {name} - ({expr})" for name, expr in zip(COUNTERS, old))
    delta = ", ".join(f"{name} = {name} + ({n}) - ({o})" for name, n, o in zip(COUNTERS, new, old))
    changed = " OR ".join(f"({n}) <> ({o})" for n, o in zip(new, old))
    moved = "OLD.conversation_id <> NEW.conversation_id"
    reordered = "OLD.created_at <> NEW.created_at OR OLD.id <> NEW.id"
    insert_sql = (f"UPDATE conversations SET message_count = message_count + 1, {add}, "
                  f"last_message_id = {latest_id('NEW.conversation_id')}, {cursor_assignments('NEW.conversation_id')} WHERE id = NEW.conversation_id")
    delete_sql = (f"UPDATE conversations SET message_count = message_count - 1, {subtract}, "
                  f"last_message_id = CASE WHEN last_message_id = OLD.id THEN "
                  f"{latest_id('OLD.conversation_id')} ELSE last_message_id END, {cursor_assignments('OLD.conversation_id')} WHERE id = OLD.conversation_id")
    update_sql = (f"UPDATE conversations SET {delta}, last_message_id = CASE WHEN {reordered} "
                  f"THEN {latest_id('NEW.conversation_id')} ELSE last_message_id END, "
                  f"{cursor_assignments('NEW.conversation_id')} WHERE id = NEW.conversation_id")
    execute = connection.exec_driver_sql
    if dialect == "sqlite":
        for name in ("insert", "delete", "update", "move"):
            execute(f"DROP TRIGGER IF EXISTS uknow_message_stats_{name}")
        execute(f"CREATE TRIGGER uknow_message_stats_insert AFTER INSERT ON messages BEGIN {insert_sql}; END")
        execute(f"CREATE TRIGGER uknow_message_stats_delete AFTER DELETE ON messages BEGIN {delete_sql}; END")
        execute(f"""CREATE TRIGGER uknow_message_stats_update
            AFTER UPDATE OF {receipt_fields}, sender_role, created_at, id, conversation_id ON messages
            WHEN NOT ({moved}) AND (({changed}) OR ({reordered}))
            BEGIN {update_sql}; END""")
        execute(f"""CREATE TRIGGER uknow_message_stats_move AFTER UPDATE OF conversation_id ON messages
            WHEN {moved} BEGIN {delete_sql}; {insert_sql}; END""")
    elif dialect == "postgresql":
        # FOR NO KEY UPDATE avoids lock upgrade deadlocks with FK key-share locks.
        execute(f"""CREATE OR REPLACE FUNCTION uknow_message_stats() RETURNS trigger
            LANGUAGE plpgsql AS $$
            BEGIN
                IF TG_OP = 'INSERT' THEN
                    PERFORM id FROM conversations WHERE id = NEW.conversation_id FOR NO KEY UPDATE;
                    {insert_sql};
                ELSIF TG_OP = 'DELETE' THEN
                    PERFORM id FROM conversations WHERE id = OLD.conversation_id FOR NO KEY UPDATE;
                    {delete_sql};
                ELSIF {moved} THEN
                    PERFORM id FROM conversations WHERE id IN (OLD.conversation_id, NEW.conversation_id)
                        ORDER BY id FOR NO KEY UPDATE;
                    {delete_sql}; {insert_sql};
                ELSIF ({changed}) OR ({reordered}) THEN
                    PERFORM id FROM conversations WHERE id = NEW.conversation_id FOR NO KEY UPDATE;
                    {update_sql};
                END IF;
                RETURN NULL;
            END; $$""")
        execute("DROP TRIGGER IF EXISTS uknow_message_stats ON messages")
        execute(f"""CREATE TRIGGER uknow_message_stats AFTER INSERT OR DELETE OR
            UPDATE OF {receipt_fields}, sender_role, created_at, id, conversation_id ON messages
            FOR EACH ROW EXECUTE FUNCTION uknow_message_stats()""")
    else:
        raise RuntimeError("Unsupported database dialect for conversation counters")


def install_on_create(_table, connection, **_kwargs):
    install_triggers(connection)


def upgrade_conversation_counters(connection):
    """Backfill once, in the caller's migration transaction."""
    columns = {c["name"] for c in inspect(connection).get_columns("conversations")}
    for name in ("message_count", *COUNTERS, "teacher_last_read_id", "student_last_read_id"):
        if name not in columns:
            connection.exec_driver_sql(f"ALTER TABLE conversations ADD COLUMN {name} BIGINT NOT NULL DEFAULT 0")
    if "last_message_id" not in columns:
        connection.exec_driver_sql("ALTER TABLE conversations ADD COLUMN last_message_id INTEGER")
    install_read_function(connection)
    dialect = connection.dialect.name
    message_columns = {c["name"] for c in inspect(connection).get_columns("messages")}
    for role in ("teacher", "student"):
        name = role + "_read_at"
        if name not in message_columns:
            storage = "VIRTUAL" if dialect == "sqlite" else "STORED"
            connection.exec_driver_sql(f"ALTER TABLE messages ADD COLUMN {name} TEXT GENERATED ALWAYS AS ({field_sql(name, dialect)}) {storage}")
    for role, predicate in (("teacher", TEACHER_UNREAD), ("student", STUDENT_UNREAD)):
        connection.exec_driver_sql(f"CREATE INDEX IF NOT EXISTS ix_messages_{role}_unread ON messages (conversation_id, id) WHERE {predicate}")
    install_triggers(connection)
    rebuild_counters(connection)


def rebuild_counters(connection):
    expressions = unread_expressions("", connection.dialect.name)
    aggregates = ", ".join(f"SUM({expr}) AS {name}" for name, expr in zip(COUNTERS, expressions))
    assignments = ", ".join(f"{name} = stats.{name}" for name in ("message_count", *COUNTERS))
    connection.exec_driver_sql("UPDATE conversations SET message_count=0, teacher_unread_count=0, "
                               "student_unread_count=0, admin_unread_count=0, last_message_id=NULL, teacher_last_read_id=0, student_last_read_id=0")
    connection.exec_driver_sql(f"""UPDATE conversations SET {assignments},
        last_message_id = {latest_id('conversations.id')}, {cursor_assignments('conversations.id')}
        FROM (SELECT conversation_id, COUNT(*) AS message_count, {aggregates}
              FROM messages GROUP BY conversation_id) AS stats
        WHERE conversations.id = stats.conversation_id""")



def upgrade_physical_receipts(connection):
    """Replace legacy/generated receipt fields with writable scalar columns.

    The upgrade runs in the existing schema transaction. A failed migration
    restores the old columns, indexes, triggers and JSON intact.
    """
    dialect = connection.dialect.name
    execute = connection.exec_driver_sql
    if dialect == "sqlite":
        for name in ("insert", "delete", "update", "move"):
            execute(f"DROP TRIGGER IF EXISTS uknow_message_stats_{name}")
    elif dialect == "postgresql":
        execute("DROP TRIGGER IF EXISTS uknow_message_stats ON messages")
    else:
        raise RuntimeError("Unsupported receipt migration dialect")
    columns = {col["name"]: col for col in inspect(connection).get_columns("messages")}
    for role in ("teacher", "student"):
        name = role + "_read_at"
        execute(f"DROP INDEX IF EXISTS ix_messages_{role}_unread")
        if columns.get(name, {}).get("computed"):
            if dialect == "postgresql":
                # Stored generated values survive dropping the expression.
                execute(f"ALTER TABLE messages ALTER COLUMN {name} DROP EXPRESSION")
            else:
                # The original JSON is still authoritative until copied below.
                execute(f"ALTER TABLE messages DROP COLUMN {name}")
                execute(f"ALTER TABLE messages ADD COLUMN {name} TEXT")
        elif name not in columns:
            execute(f"ALTER TABLE messages ADD COLUMN {name} TEXT")

    # Bounded keyset scan once at upgrade, never on the request hot path.
    cursor = None
    while True:
        where = "" if cursor is None else " WHERE id > :cursor"
        rows = connection.execute(text(
            "SELECT id, metadata_json, teacher_read_at, student_read_at FROM messages" +
            where + " ORDER BY id LIMIT 1000"), {} if cursor is None else {"cursor": cursor}).mappings().all()
        if not rows:
            break
        updates = []
        for row in rows:
            try:
                metadata = json.loads(row["metadata_json"] or "{}")
            except (ValueError, TypeError):
                continue  # preserve malformed legacy metadata verbatim
            if not isinstance(metadata, dict) or not any(
                    key in metadata for key in ("teacher_read_at", "student_read_at")):
                continue
            values = {"id": row["id"]}
            for key in ("teacher_read_at", "student_read_at"):
                old = metadata.pop(key, None)
                values[key] = row[key] if row[key] is not None else (str(old) if old is not None else None)
            values["metadata_json"] = json.dumps(metadata, ensure_ascii=False, separators=(",", ":"))
            updates.append(values)
        if updates:
            connection.execute(text("UPDATE messages SET teacher_read_at=:teacher_read_at, "
                "student_read_at=:student_read_at, metadata_json=:metadata_json WHERE id=:id"), updates)
        cursor = rows[-1]["id"]

    for role, predicate in (("teacher", TEACHER_UNREAD), ("student", STUDENT_UNREAD)):
        execute(f"CREATE INDEX IF NOT EXISTS ix_messages_{role}_unread ON messages (conversation_id, id) WHERE {predicate}")
    rebuild_counters(connection)
    install_triggers(connection)
