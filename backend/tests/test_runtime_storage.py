"""Physical separation, recovery and web availability without Runtime DB."""
from types import SimpleNamespace
from sqlalchemy import create_engine, inspect, text, event
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core import runtime_database
from app.core.database import Base
from app.migrations.runtime_split import migrate_push_subscriptions, migrate_transport_state
from app.migrations.delivery_recovery import upgrade_delivery_recovery
from app.models import PushSubscription, TransportJob, ConnectorDelivery, Message
from app.bots_gateway import transport
from app.bots_gateway.outbox import enqueue_web_delivery, record_result
from app.modules.notifications import vapid, service as push
from app.main import app
from helpers import create_conversation


def test_physical_split_and_legacy_copy(tmp_path):
    main = create_engine("sqlite:///" + str(tmp_path / "main.db"))
    runtime = create_engine("sqlite:///" + str(tmp_path / "runtime.db"))
    Base.metadata.create_all(main)
    runtime_database.RuntimeBase.metadata.create_all(runtime)
    assert not inspect(main).has_table("push_subscriptions")
    assert not inspect(main).has_table("transport_jobs")
    assert not inspect(runtime).has_table("users")
    with main.begin() as c:
        PushSubscription.__table__.create(c)
        c.execute(PushSubscription.__table__.insert().values(
            role="admin", endpoint="https://web.push.apple.com/old", p256dh="key", auth="auth",
            delivery_state="expired"))
        upgrade_delivery_recovery(c)
        c.execute(text("INSERT INTO connector_deletions (id,platform,chat_id,external_message_id,status,created_at,published_at,broker_seq) "
                       "VALUES ('del','telegram','123','456','published',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,42)"))
    with main.begin() as c:
        migrate_push_subscriptions(c, runtime)
        migrate_transport_state(c, runtime)
        migrate_push_subscriptions(c, runtime)
        migrate_transport_state(c, runtime)
    assert not inspect(main).has_table("push_subscriptions")
    assert not {"published_at","broker_seq"} & {col["name"] for col in inspect(main).get_columns("connector_deletions")}
    with Session(runtime) as db:
        assert db.query(PushSubscription).one().delivery_state == "expired"
        row = db.get(TransportJob,"del")
        assert row.broker_seq == 42 and row.state == "published"
    with main.connect() as c:
        assert c.scalar(text("SELECT status FROM connector_deletions")) == "queued"
    main.dispose()
    runtime.dispose()


def test_projection_recovery_and_no_main_sql_for_empty_queue(api):
    from app.modules.communication.accounts import sync_messenger_account
    from app.bots_gateway.operations import rpc
    from fastapi import HTTPException
    import pytest
    _, users, sessions = api
    with sessions() as db:
        chat = create_conversation(db, users["teacher-one"],users["student-one"])
        sync_messenger_account(db,users["student-one"],"telegram","student","123")
        db.flush()
        row = Message(conversation_id=chat.id,sender_id=users["teacher-one"],sender_role="teacher",text="hello")
        db.add(row)
        db.flush()
        enqueue_web_delivery(db,row,("telegram",))
        db.commit()
        job_id = db.query(ConnectorDelivery).one().id
        transport.project_pending(db,("telegram",),{})
        assert transport.candidates(db,("telegram",))[0][0] == job_id
        transport.mark_published(job_id, 42)
        queries = []
        def count(*args):
            queries.append(args[2])
        event.listen(db.get_bind(),"before_cursor_execute",count)
        try:
            assert not transport.candidates(db,("telegram",))
            assert not queries
        finally:
            event.remove(db.get_bind(),"before_cursor_execute",count)
        assert db.get(ConnectorDelivery,job_id).status == "queued"
        rpc(db,"telegram","delivery.authorize",{"id":job_id,"claim":"a"*32})
        transport.forget(job_id)
        transport.project_pending(db,("telegram",),{})
        assert transport.candidates(db,("telegram",))[0][0] == job_id
        with pytest.raises(HTTPException) as err:
            rpc(db,"telegram","delivery.authorize",{"id":job_id,"claim":"b"*32})
        assert err.value.status_code == 425
        record_result(db,db.get(ConnectorDelivery,job_id),"delivered","external")
        assert not transport.candidates(db,("telegram",))
        transport.project_pending(db,("telegram",),{})
        assert not transport.candidates(db,("telegram",))


def test_web_send_and_logout_survive_runtime_failure(api, monkeypatch):
    make_client, users, sessions = api
    from app.modules.communication.accounts import sync_messenger_account
    monkeypatch.setattr(vapid,"VAPID_PRIVATE_KEY","fake-key")
    monkeypatch.setattr(push,"_DISPATCH_POOL",SimpleNamespace(submit=lambda fn,*args:fn(*args)))
    def unavailable():
        raise OperationalError("runtime unavailable",None,Exception("offline"))
    monkeypatch.setattr(runtime_database,"RuntimeSessionLocal",unavailable)
    with sessions() as db:
        chat = create_conversation(db,users["teacher-one"],users["student-one"])
        chat_id = chat.id
        sync_messenger_account(db,users["student-one"],"telegram","student","123")
        db.commit()
    monkeypatch.setattr(app.state,"bots_gateway",SimpleNamespace(platforms=("telegram",),wake_outbox=lambda:None),raising=False)
    client = make_client()
    assert client.post("/api/auth/login",json={"username":"teacher-one","password":"teacher-password-1"}).status_code == 200
    sent = client.post(f"/api/panel/conversations/{chat_id}/messages",json={"text":"saved during outage"})
    assert sent.status_code == 201, sent.text
    with sessions() as db:
        assert db.query(Message).one().text == "saved during outage"
        assert db.query(ConnectorDelivery).one().status == "queued"
    assert client.post("/api/auth/logout").status_code == 200
