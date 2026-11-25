"""SSE is reconstructible from chat history; discard only the old technical hint."""
from sqlalchemy import text


def retire_realtime_events(connection):
    connection.execute(text("DROP TABLE IF EXISTS realtime_events"))
