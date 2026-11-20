"""Independent interactive-board object API."""

import math
import uuid

from fastapi import APIRouter, HTTPException
from sqlalchemy import func, select

from app.models import GraphObject
from app.modules.dependencies import Admin, Db

router = APIRouter(prefix="/api")


def _graph_object_dict(item: GraphObject) -> dict:
    return {
        "id": item.id, "key": item.object_key, "type": item.object_type,
        "title": item.title, "parent_id": item.parent_id, "x": item.x, "y": item.y,
    }


@router.get("/admin/graph/objects")
def graph_objects(_: Admin, db: Db):
    # Remove legacy school-structure nodes; boards now contain only user-created objects.
    objects = db.scalars(select(GraphObject).order_by(GraphObject.id)).all()
    legacy_ids = {item.id for item in objects if not item.object_key.startswith("custom:")}
    if legacy_ids:
        for item in objects:
            if item.parent_id in legacy_ids and item.object_key.startswith("custom:"):
                item.parent_id = None
        for item in objects:
            if item.id in legacy_ids:
                db.delete(item)
        db.commit()
    return [_graph_object_dict(item) for item in db.scalars(select(GraphObject).order_by(GraphObject.id)).all()]


@router.patch("/admin/graph/objects/{object_id}/position")
def update_graph_object_position(object_id: int, payload: dict, _: Admin, db: Db):
    x, y = payload.get("x"), payload.get("y")
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) or abs(value) > 100000 or not math.isfinite(value) for value in (x, y)):
        raise HTTPException(status_code=422, detail="Некорректные координаты объекта")
    item = db.get(GraphObject, object_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Объект графа не найден")
    item.x, item.y = x, y
    db.commit()
    return _graph_object_dict(item)


@router.post("/admin/graph/objects", status_code=201)
def create_graph_object(payload: dict, _: Admin, db: Db):
    title = str(payload.get("title") or "").strip()
    parent_id = payload.get("parent_id")
    object_type = str(payload.get("type") or "object").strip()
    if not title or len(title) > 160 or len(object_type) > 40:
        raise HTTPException(status_code=422, detail="Укажите название объекта")
    if parent_id is not None and db.get(GraphObject, parent_id) is None:
        raise HTTPException(status_code=404, detail="Родительский объект не найден")
    sibling_count = db.scalar(select(func.count(GraphObject.id)).where(GraphObject.parent_id == parent_id)) or 0
    parent = db.get(GraphObject, parent_id) if parent_id is not None else None
    item = GraphObject(
        object_key=f"custom:{uuid.uuid4().hex}",
        object_type=object_type, title=title, parent_id=parent_id,
        x=24 + (sibling_count % 2) * 410, y=24 + (sibling_count // 2) * 310,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return _graph_object_dict(item)


@router.delete("/admin/graph/objects/{object_id}")
def delete_graph_object(object_id: int, _: Admin, db: Db):
    item = db.get(GraphObject, object_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Объект графа не найден")

    pending = [item.id]
    descendants = []
    while pending:
        children = db.scalars(
            select(GraphObject).where(GraphObject.parent_id.in_(pending)),
        ).all()
        pending = [child.id for child in children]
        descendants.extend(children)

    for target in reversed(descendants):
        db.delete(target)
    db.delete(item)
    db.commit()
    return {"deleted": True, "deleted_count": len(descendants) + 1}


