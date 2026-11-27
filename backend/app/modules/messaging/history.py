"""Bounded keyset pages shared by personal and participant dialogs."""


def history_page(db, query, model, limit, after_id, forward):
    # Без лимита историю не выгружаем целиком.
    forward = forward or (limit is None and after_id > 0)
    order = model.id.asc() if forward else model.id.desc()
    rows = list(db.scalars(query.order_by(order).limit(limit or 100)).all())
    if not forward:
        rows.reverse()
    return rows


def sync_page(db, query, model, after_id):
    order = model.id.asc() if after_id else model.id.desc()
    rows = list(db.scalars(query.order_by(order).limit(101 if after_id else 100)).all())
    has_more = bool(after_id and len(rows) > 100)
    if has_more:
        rows = rows[:100]
    if not after_id:
        rows.reverse()
    return rows, has_more
