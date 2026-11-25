from connectors.common.spool import EventSpool


def test_unknown_external_outcome_is_not_replayed(tmp_path):
    path = tmp_path / "spool.db"
    spool = EventSpool(path, "bot")
    assert spool.delivery("one") is None
    spool.begin_delivery("one")
    spool.close()
    spool = EventSpool(path, "bot")
    assert spool.delivery("one") == {"id":"one","status":"unknown"}
    spool.begin_delivery("two")
    spool.finish_delivery("two", {"id":"two","status":"delivered","external_message_id":"123"})
    spool.select_conversation("teacher", 42)
    spool.close()
    spool = EventSpool(path, "bot")
    assert spool.delivery("two")["external_message_id"] == "123"
    assert spool.selected_conversation("teacher") == 42
    spool.close()
