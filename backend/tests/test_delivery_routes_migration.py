from sqlalchemy import create_engine, inspect, text
from app.migrations.delivery_routes import upgrade_delivery_routes


def test_upgrade_old_delivery_schema(tmp_path):
    engine = create_engine("sqlite:///" + str(tmp_path / "old.sqlite3"))
    with engine.begin() as c:
        c.execute(text("CREATE TABLE connector_deliveries (id VARCHAR(64) PRIMARY KEY, message_id INTEGER NOT NULL, platform VARCHAR(32) NOT NULL, recipient_id INTEGER NOT NULL, chat_id VARCHAR(255) NOT NULL, thread_id VARCHAR(255), UNIQUE(message_id,platform,recipient_id))"))
        c.execute(text("INSERT INTO connector_deliveries VALUES ('a',1,'alpha',2,'private',NULL)"))
        upgrade_delivery_routes(c)
        upgrade_delivery_routes(c)
        c.execute(text("INSERT INTO connector_deliveries VALUES ('b',1,'alpha',2,'group','topic')"))
        assert c.execute(text("SELECT thread_id FROM connector_deliveries WHERE id='a'")).scalar() == ""
        assert c.execute(text("SELECT count(*) FROM connector_deliveries")).scalar() == 2
        assert any(x["name"] == "uq_connector_delivery_route" for x in inspect(c).get_unique_constraints("connector_deliveries"))
