"""Compatibility import; new code uses the domain outbox."""
from app.modules.communication.outbox import (
    PENDING,
    RECOVERY_AFTER,
    TERMINAL,
    as_utc,
    authorized_job,
    claim_is_recent,
    earlier_send_pending,
    enqueue_deletion,
    enqueue_message_deletions,
    enqueue_web_delivery,
    get_job,
    job_payload,
    now_utc,
    record_result,
)

__all__ = [
    "PENDING", "TERMINAL", "RECOVERY_AFTER", "now_utc", "as_utc", "claim_is_recent",
    "earlier_send_pending", "enqueue_web_delivery", "authorized_job", "job_payload",
    "get_job", "enqueue_deletion", "enqueue_message_deletions", "record_result",
]
