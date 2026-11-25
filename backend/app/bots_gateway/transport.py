"""Runtime queue projection. Main commits are independent of this cache."""
from sqlalchemy import bindparam, delete, func, or_, select, update
from sqlalchemy.dialects.sqlite import insert

from app.core import runtime_database
from app.models import ConnectorDeletion, ConnectorDelivery, Message, TransportJob
from app.modules.communication.outbox import PENDING, RECOVERY_AFTER, now_utc

MODELS = (ConnectorDeletion, ConnectorDelivery)
PAGE = 200


def project_pending(main, platforms, cursors):
    """Read bounded pages of durable intents; write only to Runtime DB.

    A lost projection is rebuilt by scanning pending intents. Main status is
    authoritative; terminal/removed intents cannot be sent again.
    """
    records = []
    more = False
    next_cursors = {}
    for model in MODELS:
        query = select(model).where(model.platform.in_(platforms), model.status.in_(PENDING))
        cursor = cursors.get(model.__tablename__)
        if cursor:
            query = query.where(model.id > cursor)
        jobs = main.scalars(query.order_by(model.id).limit(PAGE)).all()
        mids = [j.message_id for j in jobs if isinstance(j, ConnectorDelivery) and j.message_id is not None]
        kinds = dict(main.execute(select(Message.id, Message.content_type).where(Message.id.in_(mids))).all()) if mids else {}
        if len(jobs) == PAGE:
            next_cursors[model.__tablename__] = jobs[-1].id
            more = True
        for job in jobs:
            records.append({"id": job.id, "platform": job.platform, "chat_id": job.chat_id,
                "thread_id": getattr(job, "thread_id", ""), "heavy": kinds.get(getattr(job,"message_id",None),"text") != "text",
                "created_at": job.created_at, "state": "queued"})
    # Release the Main read transaction before acquiring the runtime writer.
    main.rollback()
    if records:
        with runtime_database.RuntimeSessionLocal() as runtime:
            existing = set(runtime.scalars(select(TransportJob.id).where(TransportJob.id.in_([r["id"] for r in records]))).all())
            new = [r for r in records if r["id"] not in existing]
            if new:
                runtime.execute(insert(TransportJob).values(new).on_conflict_do_nothing(index_elements=["id"]))
                runtime.commit()
    return next_cursors, more


def candidates(main, platforms, now=None, limit=50):
    cutoff = (now or now_utc()) - RECOVERY_AFTER
    with runtime_database.RuntimeSessionLocal() as runtime:
        jobs = runtime.scalars(select(TransportJob).where(TransportJob.platform.in_(platforms),
            or_(TransportJob.state == "queued", TransportJob.published_at.is_(None),
                TransportJob.published_at <= cutoff)).order_by(TransportJob.created_at, TransportJob.id).limit(limit)).all()
        entries = []
        stale = []
        # Recheck existence and terminal status in Main before publishing.
        if not jobs:
            return []
        ids = [j.id for j in jobs]
        live = set()
        for model in MODELS:
            live.update(main.scalars(select(model.id).where(model.id.in_(ids), model.status.in_(PENDING))).all())
        main.rollback()
        for job in jobs:
            if job.id not in live:
                stale.append(job.id)
            else:
                entries.append((job.id, job.platform, job.chat_id, job.thread_id, job.state, job.heavy, job.broker_seq))
        if stale:
            runtime.execute(delete(TransportJob).where(TransportJob.id.in_(stale)))
            runtime.commit()
        return entries


def mark_published_batch(acknowledgements):
    """Flush successful broker acknowledgements in one short runtime transaction."""
    if not acknowledgements:
        return
    table = TransportJob.__table__
    stamp = now_utc()
    statement = table.update().where(table.c.id == bindparam("job_ident")).values(
        state="published", published_at=stamp,
        broker_seq=func.coalesce(bindparam("sequence", type_=table.c.broker_seq.type), table.c.broker_seq))
    with runtime_database.RuntimeSessionLocal() as runtime:
        runtime.execute(statement, [{"job_ident": ident, "sequence": sequence}
                                    for ident, sequence in acknowledgements])
        runtime.commit()


def mark_published(job_id, seq=None):
    mark_published_batch([(job_id, seq)])


def forget(job_id):
    with runtime_database.RuntimeSessionLocal() as runtime:
        runtime.execute(delete(TransportJob).where(TransportJob.id == job_id))
        runtime.commit()


def reset_sequences(platforms):
    with runtime_database.RuntimeSessionLocal() as runtime:
        runtime.execute(update(TransportJob).where(TransportJob.platform.in_(platforms)).values(
            published_at=None, broker_seq=None, state="published"))
        runtime.commit()
