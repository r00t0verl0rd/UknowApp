import { useLayoutEffect, useRef } from "react";
import Crosshair from "lucide-react/dist/esm/icons/crosshair.js";
import Plus from "lucide-react/dist/esm/icons/plus.js";
import Trash2 from "lucide-react/dist/esm/icons/trash-2.js";

function objectPosition(item) {
  return { transform: `translate3d(${item.x || 0}px, ${item.y || 0}px, 0)` };
}

function BoardObject({ item, children, createGraphObject, removeObject }) {
  return <div className="graph-board-node" data-object-id={item.id} style={objectPosition(item)}>
    <article className="graph-board-card">
      <header className="graph-board-object-header">
        <b>{item.title}</b>
        <div className="graph-board-object-actions">
          <button type="button" title="Создать вложенный объект" aria-label={`Создать объект внутри «${item.title}»`} onClick={() => createGraphObject(item.id)}><Plus /></button>
          <button type="button" title="Удалить объект" aria-label={`Удалить объект «${item.title}» и вложенные объекты`} onClick={() => removeObject(item)}><Trash2 /></button>
        </div>
      </header>
      <div className="graph-board-children">
        {children.map(child => <BoardObject key={child.id} item={child} children={child.children} createGraphObject={createGraphObject} removeObject={removeObject} />)}
      </div>
    </article>
  </div>;
}

export default function BoardsPage({
  graphObjects = [], saveGraphObjectPosition, createGraphObject, deleteGraphObject,
}) {
  const viewportRef = useRef(null);
  const worldRef = useRef(null);
  const dragRef = useRef(null);
  const frameRef = useRef(0);
  const transformRef = useRef({ zoom: 1, x: 0, y: 0 });

  const objectsByParent = new Map();
  for (const item of graphObjects) {
    const parentId = item.parent_id ?? null;
    if (!objectsByParent.has(parentId)) objectsByParent.set(parentId, []);
    objectsByParent.get(parentId).push({ ...item, children: [] });
  }
  const nodesById = new Map();
  for (const items of objectsByParent.values()) {
    for (const item of items) nodesById.set(item.id, item);
  }
  for (const item of nodesById.values()) {
    if (item.parent_id != null) nodesById.get(item.parent_id)?.children.push(item);
  }
  const roots = (objectsByParent.get(null) || []).filter(item => !nodesById.get(item.id)?.parent_id);

  useLayoutEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport) return undefined;
    const update = () => {
      const { zoom, x, y } = transformRef.current;
      if (worldRef.current) worldRef.current.style.transform = `translate3d(${x}px, ${y}px, 0) scale(${zoom})`;
    };
    const onWheel = event => {
      if (!viewport.contains(event.target)) return;
      if (event.cancelable) event.preventDefault();
      event.stopPropagation();
      const bounds = viewport.getBoundingClientRect();
      const pointX = bounds.width / 2;
      const pointY = bounds.height / 2;
      const current = transformRef.current;
      const nextZoom = Math.max(0.35, Math.min(2.5, current.zoom * Math.exp(-Math.max(-240, Math.min(240, event.deltaY)) * 0.0015)));
      if (nextZoom === current.zoom) return;
      const ratio = nextZoom / current.zoom;
      current.x = pointX - (pointX - current.x) * ratio;
      current.y = pointY - (pointY - current.y) * ratio;
      current.zoom = nextZoom;
      update();
    };
    viewport.addEventListener("wheel", onWheel, { passive: false });
    return () => viewport.removeEventListener("wheel", onWheel);
  }, []);

  function resetView() {
    transformRef.current = { zoom: 1, x: 0, y: 0 };
    if (worldRef.current) worldRef.current.style.transform = "translate3d(0, 0, 0) scale(1)";
  }

  function startObjectDrag(event) {
    if (event.button !== 0 || event.target.closest("button, a, input, select, textarea")) return;
    const handle = event.target.closest(".graph-board-object-header");
    const element = handle?.closest("[data-object-id]");
    if (!element || !event.currentTarget.contains(element)) return;
    const item = graphObjects.find(object => object.id === Number(element.dataset.objectId));
    if (!item) return;
    event.preventDefault();
    dragRef.current = {
      item, element, pointerId: event.pointerId,
      startX: event.clientX, startY: event.clientY,
      x: item.x || 0, y: item.y || 0, nextX: item.x || 0, nextY: item.y || 0,
    };
    event.currentTarget.setPointerCapture(event.pointerId);
    element.classList.add("is-object-dragging");
  }

  function moveObject(event) {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    const scale = transformRef.current.zoom || 1;
    drag.nextX = drag.x + (event.clientX - drag.startX) / scale;
    drag.nextY = drag.y + (event.clientY - drag.startY) / scale;
    if (frameRef.current) return;
    frameRef.current = requestAnimationFrame(() => {
      frameRef.current = 0;
      if (dragRef.current) dragRef.current.element.style.transform = `translate3d(${dragRef.current.nextX}px, ${dragRef.current.nextY}px, 0)`;
    });
  }

  async function endObjectDrag(event) {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    if (frameRef.current) cancelAnimationFrame(frameRef.current);
    frameRef.current = 0;
    const { nextX: x, nextY: y } = drag;
    drag.element.style.transform = `translate3d(${x}px, ${y}px, 0)`;
    drag.element.classList.remove("is-object-dragging");
    dragRef.current = null;
    if (Math.abs(x - drag.x) < 1 && Math.abs(y - drag.y) < 1) return;
    await saveGraphObjectPosition(drag.item.id, x, y);
  }

  function addObject(parentId = null) {
    const title = window.prompt("Название нового объекта");
    if (title?.trim()) createGraphObject({ title: title.trim(), parent_id: parentId });
  }

  function removeObject(item) {
    if (window.confirm(`Удалить объект «${item.title}» и все вложенные в него объекты?`)) {
      deleteGraphObject(item.id);
    }
  }

  useLayoutEffect(() => () => {
    if (frameRef.current) cancelAnimationFrame(frameRef.current);
  }, []);

  return <section className="graph-panel graph-object-panel">
    <div className="graph-legend-row">
      <div className="graph-legend"><b>Интерактивные доски</b><span>Создавайте объекты, объединяйте их в иерархии и перемещайте независимо.</span></div>
      <div className="graph-toolbar-actions">
        <button type="button" className="btn small outline" onClick={resetView} title="Сбросить масштаб"><Crosshair />Сбросить масштаб</button>
        <button type="button" className="btn primary graph-add-participant" onClick={() => addObject()}><Plus />Создать объект</button>
      </div>
    </div>
    <div
      className="graph-coordinate-viewport graph-object-viewport"
      ref={viewportRef}
      onPointerDown={startObjectDrag}
      onPointerMove={moveObject}
      onPointerUp={endObjectDrag}
      onPointerCancel={endObjectDrag}
      onLostPointerCapture={endObjectDrag}
    >
      <div className="graph-coordinate-world graph-object-world" ref={worldRef}>
        {roots.map(item => <BoardObject key={item.id} item={item} children={item.children} createGraphObject={addObject} removeObject={removeObject} />)}
        {!graphObjects.length && <div className="graph-board-empty">Доска пока пустая. Создайте первый объект.</div>}
      </div>
    </div>
  </section>;
}
