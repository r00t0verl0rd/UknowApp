from connectors.common.spool import EventSpool


def test_spool_persists_updates_and_offset_before_ack(tmp_path):
    path = tmp_path / "inbox.sqlite3"
    spool = EventSpool(path, "123")
    spool.append([("123:5", {"update_id": 5}), ("123:6", {"update_id": 6})], 7)
    spool.close()
    spool = EventSpool(path, "123")
    assert spool.cursor() == 7
    assert spool.first() == ("123:5", {"update_id": 5})
    spool.append([("123:5", {"update_id": 5})], 7)
    assert spool.count() == 2
    spool.ack("123:5")
    spool.close()
    spool = EventSpool(path, "123")
    assert spool.first() == ("123:6", {"update_id": 6})
    assert spool.cursor() == 7
    spool.close()


def test_spool_namespaces_keep_different_bots_separate(tmp_path):
    path = tmp_path / "inbox.sqlite3"
    first = EventSpool(path, "111")
    first.append([("111:5", {"update_id": 5})], 6)
    first.close()
    second = EventSpool(path, "222")
    assert second.first() is None
    assert second.cursor() is None
    second.close()
