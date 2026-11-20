import { memo, useCallback, useLayoutEffect, useMemo, useRef } from "react";
import { useBoardsState } from "../../hooks/boards/useBoardsState.js";
import Crosshair from "lucide-react/dist/esm/icons/crosshair.js";
import Plus from "lucide-react/dist/esm/icons/plus.js";
import Trash2 from "lucide-react/dist/esm/icons/trash-2.js";

function objectPosition(item, positions) {
  const position = positions.current.get(item.id);
  return {
    transform: `translate3d(${position?.x ?? item.x ?? 0}px, ${position?.y ?? item.y ?? 0}px, 0)`,
  };
}

const BoardObject = memo(function BoardObject({ item, children, positionsRef, createObject, removeObject }) {
  return <div className="graph-board-node" data-object-id={item.id} style={objectPosition(item, positionsRef)}>
    <article className="graph-board-card">
      <header className="graph-board-object-header">
        <b>{item.title}</b>
        <div className="graph-board-object-actions">
          <button type="button" title="Создать вложенный объект" aria-label={`Создать объект внутри «${item.title}»`} onClick={() => createObject(item.id)}><Plus /></button>
          <button type="button" title="Удалить объект" aria-label={`Удалить объект «${item.title}» и вложенные объекты`} onClick={() => removeObject(item)}><Trash2 /></button>
        </div>
      </header>
      <div className="graph-board-children">
        {children.map(child => <BoardObject key={child.id} item={child} children={child.children} positionsRef={positionsRef} createObject={createObject} removeObject={removeObject} />)}
      </div>
    </article>
  </div>;
});

const BoardToolbar = memo(function BoardToolbar({ onResetView, onAddObject }) {
  return <div className="graph-legend-row">
    
    <div className="graph-toolbar-actions">
      <button type="button" className="btn small outline" onClick={onResetView} title="Сбросить масштаб"><Crosshair />Сбросить масштаб</button>
      <button type="button" className="btn primary graph-add-participant" onClick={onAddObject}><Plus />Создать объект</button>
    </div>
  </div>;
});

export default function BoardsPage() {
  const { boardObjects, loading, error, clearError, createObject, deleteObject, moveObject: moveBoardObject } = useBoardsState();
  const viewportRef = useRef(null);
  const worldRef = useRef(null);
  const dragRef = useRef(null);
  const frameRef = useRef(0);
  const transformRef = useRef({ zoom: 1, x: 0, y: 0 });
  const positionsRef = useRef(new Map());
  const viewportSizeRef = useRef({ width: 0, height: 0 });

  const { roots, nodesById } = useMemo(() => {
    const objectsByParent = new Map();
    const nodesById = new Map();

    for (const item of boardObjects) {
      const node = { ...item, children: [] };
      const parentId = item.parent_id ?? null;
      if (!objectsByParent.has(parentId)) objectsByParent.set(parentId, []);
      objectsByParent.get(parentId).push(node);
      nodesById.set(node.id, node);
    }

    for (const node of nodesById.values()) {
      if (node.parent_id != null) nodesById.get(node.parent_id)?.children.push(node);
    }

    return {
      roots: (objectsByParent.get(null) || []).filter(node => !node.parent_id),
      nodesById,
    };
  }, [boardObjects]);

  useLayoutEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport) return undefined;
    const measure = () => {
      const bounds = viewport.getBoundingClientRect();
      viewportSizeRef.current = { width: bounds.width, height: bounds.height };
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(viewport);

    const update = () => {
      const { zoom, x, y } = transformRef.current;
      if (worldRef.current) worldRef.current.style.transform = `translate3d(${x}px, ${y}px, 0) scale(${zoom})`;
    };
    const onWheel = event => {
      if (!viewport.contains(event.target)) return;
      if (event.cancelable) event.preventDefault();
      event.stopPropagation();
      const pointX = viewportSizeRef.current.width / 2;
      const pointY = viewportSizeRef.current.height / 2;
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
    return () => {
      viewport.removeEventListener("wheel", onWheel);
      observer.disconnect();
    };
  }, []);

  const resetView = useCallback(() => {
    transformRef.current = { zoom: 1, x: 0, y: 0 };
    if (worldRef.current) worldRef.current.style.transform = "translate3d(0, 0, 0) scale(1)";
  }, []);

  const startObjectDrag = useCallback(event => {
    if (event.button !== 0 || event.target.closest("button, a, input, select, textarea")) return;
    const handle = event.target.closest(".graph-board-object-header");
    const element = handle?.closest("[data-object-id]");
    if (!element || !event.currentTarget.contains(element)) return;
    const item = nodesById.get(Number(element.dataset.objectId));
    if (!item) return;
    event.preventDefault();
    dragRef.current = {
      item, element, pointerId: event.pointerId,
      startX: event.clientX, startY: event.clientY,
      x: positionsRef.current.get(item.id)?.x ?? item.x ?? 0,
      y: positionsRef.current.get(item.id)?.y ?? item.y ?? 0,
      nextX: positionsRef.current.get(item.id)?.x ?? item.x ?? 0,
      nextY: positionsRef.current.get(item.id)?.y ?? item.y ?? 0,
    };
    event.currentTarget.setPointerCapture(event.pointerId);
    element.classList.add("is-object-dragging");
  }, [nodesById]);

  const moveObject = useCallback(event => {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    const scale = transformRef.current.zoom || 1;
    drag.nextX = drag.x + (event.clientX - drag.startX) / scale;
    drag.nextY = drag.y + (event.clientY - drag.startY) / scale;
    if (frameRef.current) return;
    frameRef.current = requestAnimationFrame(() => {
      frameRef.current = 0;
      if (dragRef.current === drag) {
        drag.element.style.transform = `translate3d(${drag.nextX}px, ${drag.nextY}px, 0)`;
      }
    });
  }, []);

  const endObjectDrag = useCallback(async event => {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    if (frameRef.current) cancelAnimationFrame(frameRef.current);
    frameRef.current = 0;
    const { nextX: x, nextY: y } = drag;
    drag.element.style.transform = `translate3d(${x}px, ${y}px, 0)`;
    drag.element.classList.remove("is-object-dragging");
    dragRef.current = null;
    if (Math.abs(x - drag.x) < 1 && Math.abs(y - drag.y) < 1) return;

    positionsRef.current.set(drag.item.id, { x, y });
    try {
      await moveBoardObject(drag.item.id, x, y);
    } catch {
      positionsRef.current.set(drag.item.id, { x: drag.x, y: drag.y });
      drag.element.style.transform = `translate3d(${drag.x}px, ${drag.y}px, 0)`;
    }
  }, [moveBoardObject]);

  const addObject = useCallback((parentId = null) => {
    const title = window.prompt("Название нового объекта");
    if (title?.trim()) void createObject({ title: title.trim(), parent_id: parentId }).catch(() => {});
  }, [createObject]);

  const removeObject = useCallback(item => {
    if (window.confirm(`Удалить объект «${item.title}» и все вложенные в него объекты?`)) {
      void deleteObject(item.id).catch(() => {});
    }
  }, [deleteObject]);

  useLayoutEffect(() => () => {
    if (frameRef.current) cancelAnimationFrame(frameRef.current);
  }, []);

  return <section className="graph-panel graph-object-panel">
    {error && <div className="alert alert-row" role="alert">{error}<button type="button" onClick={clearError} aria-label="Закрыть">×</button></div>}
    <BoardToolbar onResetView={resetView} onAddObject={addObject} />
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
        {roots.map(item => <BoardObject key={item.id} item={item} children={item.children} positionsRef={positionsRef} createObject={addObject} removeObject={removeObject} />)}
        {loading && !boardObjects.length && <div className="graph-board-empty">Загружаем доску…</div>}
        {!loading && !boardObjects.length && <div className="graph-board-empty">Доска пока пустая. Создайте первый объект.</div>}
      </div>
    </div>
  </section>;
}
