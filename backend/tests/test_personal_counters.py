from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, insert, select, update

from app.models import PersonalConversation, PersonalMessage
from app.modules.personal_chat.service import personal_stats


def test_personal_counters_bulk_receipts_delete_and_rollback(api):
    _, users, sessions = api
    with sessions() as db:
        item = PersonalConversation(participant_id=users["teacher-one"])
        db.add(item)
        db.flush()
        cid = item.id
        now = datetime.now(UTC)
        db.execute(insert(PersonalMessage), [
            {"conversation_id": cid, "sender_role": "teacher", "text": "first", "created_at": now},
            {"conversation_id": cid, "sender_role": "admin", "text": "second", "created_at": now + timedelta(seconds=1)},
            {"conversation_id": cid, "sender_role": "teacher", "text": "third", "created_at": now + timedelta(seconds=2)},
        ])
        db.commit()

        def counters():
            row = personal_stats(db, [cid])[cid]
            return row.admin_unread_count, row.participant_unread_count, row.last_message_at

        assert counters()[:2] == (2, 1)
        latest = counters()[2]
        first, second, third = db.scalars(select(PersonalMessage.id).where(
            PersonalMessage.conversation_id == cid).order_by(PersonalMessage.id)).all()
        db.execute(update(PersonalMessage).where(PersonalMessage.id == third).values(admin_read_at=now))
        assert counters()[:2] == (1, 1)
        db.rollback()
        assert counters()[:2] == (2, 1)
        db.execute(update(PersonalMessage).where(PersonalMessage.id == third).values(admin_read_at=now))
        db.execute(update(PersonalMessage).where(PersonalMessage.id == third).values(admin_read_at=now))
        assert counters()[:2] == (1, 1)
        db.execute(delete(PersonalMessage).where(PersonalMessage.id == third))
        assert counters()[:2] == (1, 1)
        assert counters()[2] < latest
        db.execute(delete(PersonalMessage).where(PersonalMessage.id == first))
        db.execute(delete(PersonalMessage).where(PersonalMessage.id == second))
        db.commit()
        assert counters() == (0, 0, None)
