"""Compatibility import; new code uses the domain outbox."""
from app.modules.communication.outbox import (
    PENDING, TERMINAL, RECOVERY_AFTER, now_utc, as_utc, claim_is_recent,
    earlier_send_pending, enqueue_web_delivery, authorized_job, job_payload,
    get_job, enqueue_deletion, enqueue_message_deletions, record_result,
)
