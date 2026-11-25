"""Transactional, exact conversation summaries without history scans on reads.

Keep per-message receipts (visible-window reads may leave holes). SQL triggers
cover ORM, bulk SQL, imports and rollback. No process cache can become stale.
"""
from sqlalchemy import inspect

COUNTERS = ("teacher_unread_count", "student_unread_count", "admin_unread_count")


def unread_expressions(prefix, dialect):
    def missing(key):
        column = prefix + "metadata_json"
        if dialect == "sqlite":
            return (f"(CASE WHEN json_valid({column}) THEN "
                    f"json_extract({column}, '$.{key}') ELSE NULL END) IS NULL")
        return f"uknow_read_field({column}, '{key}') IS NULL"

    role = prefix + "sender_role"
    teacher = f"({role} IN ('student','admin') AND {missing('teacher_read_at')})"
    student = f"({role} IN ('teacher','admin') AND {missing('student_read_at')})"
    admin = f"({role} IN ('teacher','student') AND ({teacher} OR {student}))"
    return [f"CASE WHEN {condition} THEN 1 ELSE 0 END" for condition in (teacher, student, admin)]


def latest_id(conversation):
    return ("(SELECT id FROM messages WHERE conversation_id = " + conversation +
            " ORDER BY created_at DESC, id DESC LIMIT 1)")


def install_triggers(connection):
    dialect = connection.dialect.name
    new = unread_expressions("NEW.", dialect)
    old = unread_expressions("OLD.", dialect)
    add = ", ".join(f"{name} = {name} + ({expr})" for name, expr in zip(COUNTERS, new))
    subtract = ", ".join(f"{name} = {name} - ({expr})" for name, expr in zip(COUNTERS, old))
    delta = ", ".join(f"{name} = {name} + ({n}) - ({o})" for name, n, o in zip(COUNTERS, new, old))
    changed = " OR ".join(f"({n}) <> ({o})" for n, o in zip(new, old))
    moved = "OLD.conversation_id <> NEW.conversation_id"
    reordered = "OLD.created_at <> NEW.created_at OR OLD.id <> NEW.id"
    insert_sql = (f"UPDATE conversations SET message_count = message_count + 1, {add}, "
                  f"last_message_id = {latest_id('NEW.conversation_id')} WHERE id = NEW.conversation_id")
    delete_sql = (f"UPDATE conversations SET message_count = message_count - 1, {subtract}, "
                  f"last_message_id = CASE WHEN last_message_id = OLD.id THEN "
                  f"{latest_id('OLD.conversation_id')} ELSE last_message_id END WHERE id = OLD.conversation_id")
    update_sql = (f"UPDATE conversations SET {delta}, last_message_id = CASE WHEN {reordered} "
                  f"THEN {latest_id('NEW.conversation_id')} ELSE last_message_id END "
                  f"WHERE id = NEW.conversation_id")
    execute = connection.exec_driver_sql
    if dialect == "sqlite":
        for name in ("insert", "delete", "update", "move"):
            execute(f"DROP TRIGGER IF EXISTS uknow_message_stats_{name}")
        execute(f"CREATE TRIGGER uknow_message_stats_insert AFTER INSERT ON messages BEGIN {insert_sql}; END")
        execute(f"CREATE TRIGGER uknow_message_stats_delete AFTER DELETE ON messages BEGIN {delete_sql}; END")
        execute(f"""CREATE TRIGGER uknow_message_stats_update
            AFTER UPDATE OF metadata_json, sender_role, created_at, id, conversation_id ON messages
            WHEN NOT ({moved}) AND (({changed}) OR ({reordered}))
            BEGIN {update_sql}; END""")
        execute(f"""CREATE TRIGGER uknow_message_stats_move AFTER UPDATE OF conversation_id ON messages
            WHEN {moved} BEGIN {delete_sql}; {insert_sql}; END""")
    elif dialect == "postgresql":
        execute("""CREATE OR REPLACE FUNCTION uknow_read_field(value text, field text)
            RETURNS text LANGUAGE plpgsql IMMUTABLE AS $$
            BEGIN RETURN value::jsonb ->> field;
            EXCEPTION WHEN invalid_text_representation THEN RETURN NULL;
            END; $$""")
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
        execute("""CREATE TRIGGER uknow_message_stats AFTER INSERT OR DELETE OR
            UPDATE OF metadata_json, sender_role, created_at, id, conversation_id ON messages
            FOR EACH ROW EXECUTE FUNCTION uknow_message_stats()""")
    else:
        raise RuntimeError("Unsupported database dialect for conversation counters")


def install_on_create(_table, connection, **_kwargs):
    install_triggers(connection)


def upgrade_conversation_counters(connection):
    """Backfill once, in the caller's migration transaction."""
    columns = {c["name"] for c in inspect(connection).get_columns("conversations")}
    for name in ("message_count", *COUNTERS):
        if name not in columns:
            connection.exec_driver_sql(f"ALTER TABLE conversations ADD COLUMN {name} BIGINT NOT NULL DEFAULT 0")
    if "last_message_id" not in columns:
        connection.exec_driver_sql("ALTER TABLE conversations ADD COLUMN last_message_id INTEGER")
    install_triggers(connection)
    expressions = unread_expressions("", connection.dialect.name)
    aggregates = ", ".join(f"SUM({expr}) AS {name}" for name, expr in zip(COUNTERS, expressions))
    assignments = ", ".join(f"{name} = stats.{name}" for name in ("message_count", *COUNTERS))
    connection.exec_driver_sql("UPDATE conversations SET message_count=0, teacher_unread_count=0, "
                               "student_unread_count=0, admin_unread_count=0, last_message_id=NULL")
    connection.exec_driver_sql(f"""UPDATE conversations SET {assignments},
        last_message_id = {latest_id('conversations.id')}
        FROM (SELECT conversation_id, COUNT(*) AS message_count, {aggregates}
              FROM messages GROUP BY conversation_id) AS stats
        WHERE conversations.id = stats.conversation_id""")
