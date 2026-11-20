import { useEffect, useLayoutEffect, useRef, useState } from "react";
import ChevronRight from "lucide-react/dist/esm/icons/chevron-right.js";
import GraduationCap from "lucide-react/dist/esm/icons/graduation-cap.js";
import Link2Off from "lucide-react/dist/esm/icons/link-2-off.js";
import Pencil from "lucide-react/dist/esm/icons/pencil.js";
import Plus from "lucide-react/dist/esm/icons/plus.js";
import Smile from "lucide-react/dist/esm/icons/smile.js";
import { createInnerGraphCoordinateSystem, createOuterCoordinateSystem } from "./graphCoordinates.js";

const STUDENT_LAYOUT_KEY = "uknowapp-graph-student-layout";
const TEACHER_STUDENT_LAYOUT_KEY = "uknowapp-teacher-graph-student-layout";
const EMPTY_CLOUD_POSITIONS = [];
const GRAPH_GRID_SIZE = 12;

function readStudentLayout() {
  try {
    const layout = JSON.parse(localStorage.getItem(STUDENT_LAYOUT_KEY) || "{}");
    return layout && typeof layout === "object" && !Array.isArray(layout) ? layout : {};
  } catch {
    return {};
  }
}

function positionMap(positions = []) {
  return Object.fromEntries(positions.map(({ teacher_id, x, y }) => [teacher_id, { x, y }]));
}

function positionStyle(position) {
  return { transform: `translate3d(${position?.x || 0}px, ${position?.y || 0}px, 0)` };
}

function boundsRect(elementOrRect) {
  return typeof elementOrRect.getBoundingClientRect === "function" ? elementOrRect.getBoundingClientRect() : elementOrRect;
}

function findFreeGridPosition(element, siblings, currentPosition, boundsElement = element.parentElement, zoom = 1) {
  const bounds = boundsRect(boundsElement);
  const rect = element.getBoundingClientRect();
  const gridStep = GRAPH_GRID_SIZE / zoom;
  const maxX = Math.max(0, (bounds.right - rect.right) / zoom + currentPosition.x);
  const maxY = Math.max(0, (bounds.bottom - rect.bottom) / zoom + currentPosition.y);
  const siblingRects = [];
  siblings.forEach(other => {
    if (other !== element) siblingRects.push(other.getBoundingClientRect());
  });
  const collides = (candidateX, candidateY) => {
    const left = rect.left + (candidateX - currentPosition.x) * zoom;
    const top = rect.top + (candidateY - currentPosition.y) * zoom;
    const right = left + rect.width;
    const bottom = top + rect.height;
    if (left < bounds.left - 1 || top < bounds.top - 1 || right > bounds.right + 1 || bottom > bounds.bottom + 1) return true;
    return siblingRects.some(otherRect =>
      left < otherRect.right - 1 && right > otherRect.left + 1 && top < otherRect.bottom - 1 && bottom > otherRect.top + 1
    );
  };

  if (!collides(currentPosition.x, currentPosition.y)) return currentPosition;
  const maxSteps = Math.ceil(Math.max(bounds.width, bounds.height, 1200) / GRAPH_GRID_SIZE);
  for (let radius = 1; radius <= maxSteps; radius += 1) {
    for (let step = -radius; step <= radius; step += 1) {
      const candidates = [
        [step, -radius], [step, radius], [-radius, step], [radius, step],
      ];
      for (const [column, row] of candidates) {
        const x = currentPosition.x + column * gridStep;
        const y = currentPosition.y + row * gridStep;
        if (x < 0 || y < 0 || x > maxX || y > maxY) continue;
        if (!collides(x, y)) return { x, y };
      }
    }
  }
  return { x: Math.min(maxX, Math.max(0, currentPosition.x)), y: Math.min(maxY, Math.max(0, currentPosition.y)) };
}

function clampElementPosition(element, position, boundsElement) {
  const rect = element.getBoundingClientRect();
  const bounds = boundsRect(boundsElement);
  const clampDelta = (start, end, min, max) => end - start > max - min
    ? (min + max - start - end) / 2
    : start < min ? min - start : end > max ? max - end : 0;
  return {
    x: position.x + clampDelta(rect.left, rect.right, bounds.left, bounds.right),
    y: position.y + clampDelta(rect.top, rect.bottom, bounds.top, bounds.bottom),
  };
}

function dragPosition(drag, clientX, clientY, outer, inner) {
  const bounds = drag.boundaryRect;
  const element = drag.elementRect;
  const pointer = outer.toLocal(clientX, clientY);
  const graphPointer = inner.toGraphPoint(pointer);
  const delta = { x: graphPointer.x - drag.startGraph.x, y: graphPointer.y - drag.startGraph.y };
  const zoom = inner.zoom;
  const clamp = (value, min, max) => min > max ? (min + max) / 2 : Math.max(min, Math.min(max, value));
  const minX = outer.deltaToLocal(bounds.left - element.left, 0).x / zoom;
  const maxX = outer.deltaToLocal(bounds.right - element.right, 0).x / zoom;
  const minY = outer.deltaToLocal(0, bounds.top - element.top).y / zoom;
  const maxY = outer.deltaToLocal(0, bounds.bottom - element.bottom).y / zoom;
  const snapped = inner.snapPoint({ x: drag.x + delta.x, y: drag.y + delta.y }, outer);
  return { x: clamp(snapped.x, drag.x + minX, drag.x + maxX), y: clamp(snapped.y, drag.y + minY, drag.y + maxY) };
}

function TeacherBranch({ teacher, students, studentLayout, studentsCollapsed = false, isOwner = false, cloudLayout, cloudStack, setCollapsedTeacherIds, openEdit, setTeacherId, setStudentId, allStudents, setModal, unassignStudent }) {
  const content = <>
    <div className="person-card teacher-card" {...(!isOwner ? { "data-drag-type": "cloud", "data-drag-id": teacher.id } : {})}>
      <div className="person-main"><div className="avatar teacher-avatar"><GraduationCap /></div><div className="person-info"><b>{teacher.full_name}</b><small>{isOwner ? "Вы · Учитель" : "Учитель"} · {students.length} учен.</small></div></div>
      {!isOwner && <div className="person-actions">
        <button className={`danger-icon teacher-collapse-btn${studentsCollapsed ? "" : " is-expanded"}`} title={studentsCollapsed ? "Показать учеников" : "Скрыть учеников"} aria-label={studentsCollapsed ? "Показать учеников" : "Скрыть учеников"} aria-expanded={!studentsCollapsed} onClick={() => setCollapsedTeacherIds(current => { const next = new Set(current); if (next.has(teacher.id)) next.delete(teacher.id); else next.add(teacher.id); return next; })}><ChevronRight /></button>
        <button title="Редактировать" onClick={() => openEdit(teacher)}><Pencil /></button>
      </div>}
    </div>
    {!isOwner && !studentsCollapsed && <button className="add-student" onClick={() => { setTeacherId(String(teacher.id)); setStudentId(allStudents[0]?.id ? String(allStudents[0].id) : ""); setModal({ mode: "assign" }); }}><Plus />Назначить ученика</button>}
    {!studentsCollapsed && <div className="student-list">
      {students.map(student => <div
        className="person-card student-card"
        key={student.id}
        style={positionStyle(studentLayout[student.id])}
        data-drag-type="student"
        data-drag-id={student.id}
      >
        <div className="person-main"><div className="avatar student-avatar"><Smile /></div><div className="person-info"><b>{student.full_name}</b>{student.additional_info && <small className="student-additional-info">{student.additional_info}</small>}</div></div>
        {!isOwner && <div className="person-actions">
          <button type="button" className="icon-btn graph-person-action" title="Открепить от учителя" aria-label={"Открепить " + student.full_name + " от учителя"} onClick={() => unassignStudent(student)}><Link2Off /></button>
          <button type="button" className="icon-btn graph-person-action" title="Редактировать" onClick={() => openEdit(student)}><Pencil /></button>
        </div>}
      </div>)}
      {!students.length && <div className="empty-students">{isOwner ? "Пока нет назначенных учеников" : "Нет назначенных учеников"}</div>}
    </div>}
  </>;

  if (isOwner) return content;
  return (
    <section
      className={`teacher-branch${studentsCollapsed ? " is-collapsed" : ""}`}
      key={teacher.id}
      style={{ ...positionStyle(cloudLayout[teacher.id]), zIndex: cloudStack[teacher.id] || 0 }}
    >
      {content}
    </section>
  );
}

export default function StructurePage({ profile, teacherGraph, overview, openCreate, allTeachers, studentsByTeacherId, collapsedTeacherIds, setCollapsedTeacherIds, openEdit, setTeacherId, setStudentId, allStudents, setModal, unassignedStudents, unassignStudent, saveCloudPosition }) {
  const cloudPositions = overview?.cloud_positions || EMPTY_CLOUD_POSITIONS;
  const cloudPositionsInitializedRef = useRef(false);
  const [cloudLayout, setCloudLayout] = useState(() => positionMap(cloudPositions));
  const cloudLayoutRef = useRef(cloudLayout);
  const [cloudStack, setCloudStack] = useState({});
  const cloudStackRef = useRef(0);
  const [studentLayout, setStudentLayout] = useState(readStudentLayout);
  const studentLayoutRef = useRef(studentLayout);
  const [graphViewportHeight, setGraphViewportHeight] = useState(() => Math.max(360, Math.min(900, window.innerHeight * 0.7)));
  const [teacherStudentLayout, setTeacherStudentLayout] = useState(() => {
    try {
      const layout = JSON.parse(localStorage.getItem(TEACHER_STUDENT_LAYOUT_KEY) || "{}");
      return layout && typeof layout === "object" && !Array.isArray(layout) ? layout : {};
    } catch {
      return {};
    }
  });
  const teacherStudentLayoutRef = useRef(teacherStudentLayout);
  const dragRef = useRef(null);
  const frameRef = useRef(0);
  const transformFrameRef = useRef(0);
  const graphViewportRef = useRef(null);
  const graphWorldRef = useRef(null);
  const outerCoordinatesRef = useRef(createOuterCoordinateSystem(GRAPH_GRID_SIZE));
  const innerCoordinatesRef = useRef(createInnerGraphCoordinateSystem());
  const touchPointersRef = useRef(new Map());
  const pinchRef = useRef(null);

  useEffect(() => {
    if (!cloudPositionsInitializedRef.current) {
      cloudPositionsInitializedRef.current = true;
      return;
    }
    const next = positionMap(cloudPositions);
    cloudLayoutRef.current = next;
    setCloudLayout(next);
  }, [cloudPositions]);

  useLayoutEffect(() => {
    const viewport = graphViewportRef.current;
    if (!viewport) return undefined;
    const outer = outerCoordinatesRef.current;
    let boundsFrame = 0;
    const updateBounds = () => {
      boundsFrame = 0;
      outer.update(viewport);
    };
    const scheduleBoundsUpdate = () => {
      if (!boundsFrame) boundsFrame = requestAnimationFrame(updateBounds);
    };
    const updateViewportSize = () => {
      setGraphViewportHeight(Math.max(360, Math.min(900, window.innerHeight * 0.7)));
      scheduleBoundsUpdate();
    };
    updateBounds();
    if (graphWorldRef.current) graphWorldRef.current.style.transform = innerCoordinatesRef.current.transform();
    const observer = typeof ResizeObserver !== "undefined" ? new ResizeObserver(scheduleBoundsUpdate) : null;
    observer?.observe(viewport);
    window.addEventListener("resize", updateViewportSize, { passive: true });
    window.addEventListener("scroll", scheduleBoundsUpdate, { passive: true, capture: true });
    return () => {
      observer?.disconnect();
      window.removeEventListener("resize", updateViewportSize);
      window.removeEventListener("scroll", scheduleBoundsUpdate, true);
      if (boundsFrame) cancelAnimationFrame(boundsFrame);
    };
  }, [profile?.role]);

  useLayoutEffect(() => {
    const isAdmin = profile?.role === "admin";
    const isTeacher = profile?.role === "teacher";
    if (!isAdmin && !isTeacher) return;

    const previousClouds = cloudLayoutRef.current;
    const previousStudents = studentLayoutRef.current;
    const previousTeacherStudents = teacherStudentLayoutRef.current;
    const nextClouds = { ...previousClouds };
    const nextStudents = { ...previousStudents };
    const nextTeacherStudents = { ...previousTeacherStudents };

    const allocateGroup = (selector, layout) => {
      const elements = [...document.querySelectorAll(selector)];
      elements.forEach(element => {
        const handle = element.matches("[data-drag-id]") ? element : element.querySelector("[data-drag-id]");
        const id = handle?.dataset.dragId;
        if (!id) return;
        const boundsElement = handle.dataset.dragType === "cloud" ? outerCoordinatesRef.current.getBounds() : element.parentElement;
        if (layout[id]) {
          const position = clampElementPosition(element, layout[id], boundsElement);
          if (position.x !== layout[id].x || position.y !== layout[id].y) {
            layout[id] = position;
            element.style.transform = `translate3d(${position.x}px, ${position.y}px, 0)`;
          }
          return;
        }
        const siblings = elements.filter(other => other !== element && other.parentElement === element.parentElement);
        const position = findFreeGridPosition(element, siblings, { x: 0, y: 0 }, boundsElement);
        element.style.transform = `translate3d(${position.x}px, ${position.y}px, 0)`;
        layout[id] = position;
      });
    };



    if (isAdmin) {
      allocateGroup(".graph-panel:not(.is-teacher-view) .teacher-grid > .teacher-branch", nextClouds);
      allocateGroup(".graph-panel:not(.is-teacher-view) .student-list > .student-card", nextStudents);
      allocateGroup(".graph-panel:not(.is-teacher-view) .unassigned-grid > .student-card", nextStudents);
    } else {
      allocateGroup(".graph-panel.is-teacher-view .student-list > .student-card", nextTeacherStudents);
    }

    const cloudsChanged = Object.keys(nextClouds).some(id => previousClouds[id]?.x !== nextClouds[id]?.x || previousClouds[id]?.y !== nextClouds[id]?.y);
    const studentsChanged = Object.keys(nextStudents).some(id => previousStudents[id]?.x !== nextStudents[id]?.x || previousStudents[id]?.y !== nextStudents[id]?.y);
    const teacherStudentsChanged = Object.keys(nextTeacherStudents).some(id => previousTeacherStudents[id]?.x !== nextTeacherStudents[id]?.x || previousTeacherStudents[id]?.y !== nextTeacherStudents[id]?.y);

    if (cloudsChanged) {
      cloudLayoutRef.current = nextClouds;
      setCloudLayout(nextClouds);
      Object.entries(nextClouds).forEach(([id, position]) => {
        if (previousClouds[id]?.x !== position.x || previousClouds[id]?.y !== position.y) {
          saveCloudPosition(id, position.x, position.y);
        }
      });
    }
    if (studentsChanged) {
      studentLayoutRef.current = nextStudents;
      setStudentLayout(nextStudents);
      try { localStorage.setItem(STUDENT_LAYOUT_KEY, JSON.stringify(nextStudents)); } catch {}
    }
    if (teacherStudentsChanged) {
      teacherStudentLayoutRef.current = nextTeacherStudents;
      setTeacherStudentLayout(nextTeacherStudents);
      try { localStorage.setItem(TEACHER_STUDENT_LAYOUT_KEY, JSON.stringify(nextTeacherStudents)); } catch {}
    }
  }, [profile?.role, allTeachers, studentsByTeacherId, unassignedStudents, teacherGraph, saveCloudPosition]);




  function scheduleGraphTransform() {
    if (transformFrameRef.current) return;
    transformFrameRef.current = requestAnimationFrame(() => {
      transformFrameRef.current = 0;
      const world = graphWorldRef.current;
      if (world) world.style.transform = innerCoordinatesRef.current.transform();
    });
  }

  function handleGraphWheel(event) {
    event.preventDefault();
    const bounds = outerCoordinatesRef.current.getBounds();
    const point = outerCoordinatesRef.current.toLocal(
      bounds.left + bounds.width / 2,
      bounds.top + bounds.height / 2,
    );
    const delta = event.deltaY * (event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? bounds.height : 1);
    const factor = Math.exp(-Math.max(-240, Math.min(240, delta)) * 0.0015);
    if (innerCoordinatesRef.current.zoomAt(point, factor)) scheduleGraphTransform();
  }

  function handleGraphPointerDownCapture(event) {
    if (event.pointerType !== "touch") return;
    const pointers = touchPointersRef.current;
    pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
    if (pointers.size < 2) return;
    if (dragRef.current) {
      const activeDrag = dragRef.current;
      activeDrag.element.style.transform = `translate3d(${activeDrag.x}px, ${activeDrag.y}px, 0)`;
      activeDrag.element.classList.remove("is-dragging");
      activeDrag.element.style.willChange = "";
      activeDrag.element.style.transition = "";
      dragRef.current = null;
    }
    if (frameRef.current) cancelAnimationFrame(frameRef.current);
    frameRef.current = 0;
    const iterator = pointers.values();
    const first = iterator.next().value;
    const second = iterator.next().value;
    const midpoint = outerCoordinatesRef.current.toLocal(
      (first.x + second.x) / 2,
      (first.y + second.y) / 2,
    );
    pinchRef.current = {
      distance: Math.hypot(second.x - first.x, second.y - first.y),
      midpoint,
    };
    try { event.currentTarget.setPointerCapture(event.pointerId); } catch {}
  }

  function handleGraphPointerMoveCapture(event) {
    const pointers = touchPointersRef.current;
    if (!pointers.has(event.pointerId)) return;
    const pointer = pointers.get(event.pointerId);
    if (!pointer) return;
    pointer.x = event.clientX;
    pointer.y = event.clientY;
    if (pointers.size < 2 || !pinchRef.current) return;
    const iterator = pointers.values();
    const first = iterator.next().value;
    const second = iterator.next().value;
    const midpoint = outerCoordinatesRef.current.toLocal(
      (first.x + second.x) / 2,
      (first.y + second.y) / 2,
    );
    const distance = Math.hypot(second.x - first.x, second.y - first.y);
    const pinch = pinchRef.current;
    const inner = innerCoordinatesRef.current;
    inner.panBy(midpoint.x - pinch.midpoint.x, midpoint.y - pinch.midpoint.y);
    if (pinch.distance > 0 && distance > 0) inner.zoomAt(midpoint, distance / pinch.distance);
    pinch.distance = distance;
    pinch.midpoint = midpoint;
    scheduleGraphTransform();
  }

  function handleGraphPointerUpCapture(event) {
    touchPointersRef.current.delete(event.pointerId);
    if (touchPointersRef.current.size < 2) pinchRef.current = null;
  }

  function startDrag(event, handle) {
    if (pinchRef.current || event.button !== 0 || event.target.closest("button, a, input, select, textarea")) return;
    const type = handle.dataset.dragType;
    const id = handle.dataset.dragId;
    if (!type || !id) return;

    event.preventDefault();
    const captureElement = event.currentTarget;
    const element = type === "cloud" ? handle.closest(".teacher-branch") : handle;
    if (type === "cloud") element.style.zIndex = String(++cloudStackRef.current);
    const teacherView = type === "student" && Boolean(handle.closest(".is-teacher-view"));
    const layout = type === "cloud" ? cloudLayoutRef.current : teacherView ? teacherStudentLayoutRef.current : studentLayoutRef.current;
    const position = layout[id] || { x: 0, y: 0 };
    const outer = outerCoordinatesRef.current;
    const boundsElement = type === "cloud" ? outer.getBounds() : element.parentElement;
    dragRef.current = {
      type, id, element, teacherView, pointerId: event.pointerId,
      startGraph: innerCoordinatesRef.current.toGraphPoint(outer.toLocal(event.clientX, event.clientY)),
      x: position.x, y: position.y,
      nextX: position.x, nextY: position.y,
      elementRect: element.getBoundingClientRect(),
      boundaryRect: type === "cloud" ? boundsElement : boundsElement.getBoundingClientRect(),
    };
    captureElement.setPointerCapture(event.pointerId);
    element.classList.add("is-dragging");
    element.style.willChange = "transform";
    element.style.transition = "none";
  }

  function handlePointerDown(event) {
    const handle = event.target.closest("[data-drag-type]");
    if (handle && event.currentTarget.contains(handle)) startDrag(event, handle);
  }

  function moveDrag(event) {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    if (pinchRef.current) return;
    const position = dragPosition(drag, event.clientX, event.clientY, outerCoordinatesRef.current, innerCoordinatesRef.current);
    drag.nextX = position.x;
    drag.nextY = position.y;
    if (!frameRef.current) {
      frameRef.current = requestAnimationFrame(() => {
        frameRef.current = 0;
        const active = dragRef.current;
        if (active) active.element.style.transform = `translate3d(${active.nextX}px, ${active.nextY}px, 0)`;
      });
    }
  }

  function endDrag(event) {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    if (frameRef.current) cancelAnimationFrame(frameRef.current);
    frameRef.current = 0;
    let { x, y } = event.type === "pointerup"
      ? dragPosition(drag, event.clientX, event.clientY, outerCoordinatesRef.current, innerCoordinatesRef.current)
      : { x: drag.nextX, y: drag.nextY };
    const hasMoved = Math.abs(x - drag.x) >= 1 || Math.abs(y - drag.y) >= 1;
    drag.element.style.transform = `translate3d(${x}px, ${y}px, 0)`;
    const currentRect = drag.element.getBoundingClientRect();
    const siblings = hasMoved ? (drag.type === "cloud"
      ? drag.element.parentElement.querySelectorAll(":scope > .teacher-branch")
      : drag.element.parentElement.querySelectorAll(":scope > .student-card")) : [];
    let swapTarget = null;
    let targetRatio = 0;
    for (const sibling of siblings) {
      if (sibling === drag.element) continue;
      const rect = sibling.getBoundingClientRect();
      const overlapWidth = Math.max(0, Math.min(currentRect.right, rect.right) - Math.max(currentRect.left, rect.left));
      const overlapHeight = Math.max(0, Math.min(currentRect.bottom, rect.bottom) - Math.max(currentRect.top, rect.top));
      const overlapArea = overlapWidth * overlapHeight;
      const smallerArea = Math.min(currentRect.width * currentRect.height, rect.width * rect.height);
      const ratio = smallerArea ? overlapArea / smallerArea : 0;
      if (ratio > 0.5 && ratio > targetRatio) {
        swapTarget = sibling;
        targetRatio = ratio;
      }
    }
    if (!swapTarget && hasMoved) {
      const siblings = drag.type === "cloud"
        ? drag.element.parentElement.querySelectorAll(":scope > .teacher-branch")
        : drag.element.parentElement.querySelectorAll(":scope > .student-card");
      const boundsElement = drag.type === "cloud" ? outerCoordinatesRef.current.getBounds() : drag.element.parentElement;
      const safePosition = findFreeGridPosition(drag.element, siblings, { x, y }, boundsElement, innerCoordinatesRef.current.zoom);
      x = safePosition.x;
      y = safePosition.y;
    }
    const targetHandle = swapTarget && (drag.type === "cloud" ? swapTarget.querySelector('[data-drag-type="cloud"]') : swapTarget);
    const targetId = targetHandle?.dataset.dragId;
    let targetPosition = null;
    if (swapTarget && targetId) {
      const targetRect = swapTarget.getBoundingClientRect();
      const layout = drag.type === "cloud" ? cloudLayoutRef.current : drag.teacherView ? teacherStudentLayoutRef.current : studentLayoutRef.current;
      const previousTarget = layout[targetId] || { x: 0, y: 0 };
      targetPosition = {
        id: targetId,
        x: previousTarget.x + outerCoordinatesRef.current.deltaToLocal(drag.elementRect.left - targetRect.left, drag.elementRect.top - targetRect.top).x / innerCoordinatesRef.current.zoom,
        y: previousTarget.y + outerCoordinatesRef.current.deltaToLocal(drag.elementRect.left - targetRect.left, drag.elementRect.top - targetRect.top).y / innerCoordinatesRef.current.zoom,
      };
      const swapDelta = outerCoordinatesRef.current.deltaToLocal(targetRect.left - currentRect.left, targetRect.top - currentRect.top);
      x += swapDelta.x / innerCoordinatesRef.current.zoom;
      y += swapDelta.y / innerCoordinatesRef.current.zoom;
    }
    drag.element.style.transform = `translate3d(${x}px, ${y}px, 0)`;
    drag.element.classList.remove("is-dragging");
    drag.element.style.willChange = "";
    drag.element.style.transition = "";
    dragRef.current = null;
    if (!targetPosition && Math.abs(x - drag.x) < 1 && Math.abs(y - drag.y) < 1) return;

    if (drag.type === "cloud") {
      const next = { ...cloudLayoutRef.current, [drag.id]: { x, y } };
      if (targetPosition) next[targetPosition.id] = { x: targetPosition.x, y: targetPosition.y };
      cloudLayoutRef.current = next;
      setCloudLayout(next);
      setCloudStack(current => ({ ...current, [drag.id]: cloudStackRef.current }));
      saveCloudPosition(drag.id, x, y);
      if (targetPosition) saveCloudPosition(targetPosition.id, targetPosition.x, targetPosition.y);
      return;
    }

    const layoutRef = drag.teacherView ? teacherStudentLayoutRef : studentLayoutRef;
    const setLayout = drag.teacherView ? setTeacherStudentLayout : setStudentLayout;
    const storageKey = drag.teacherView ? TEACHER_STUDENT_LAYOUT_KEY : STUDENT_LAYOUT_KEY;
    const next = { ...layoutRef.current, [drag.id]: { x, y } };
    if (targetPosition) next[targetPosition.id] = { x: targetPosition.x, y: targetPosition.y };
    layoutRef.current = next;
    setLayout(next);
    try {
      localStorage.setItem(storageKey, JSON.stringify(next));
    } catch {
      // Student arrangement remains active for this page session if storage is unavailable.
    }
  }

  useEffect(() => () => {
    if (frameRef.current) cancelAnimationFrame(frameRef.current);
    if (transformFrameRef.current) cancelAnimationFrame(transformFrameRef.current);
    touchPointersRef.current.clear();
    pinchRef.current = null;
  }, []);

  return (
    <>
      {profile?.role === "teacher" && <section className="graph-panel is-teacher-view">
        <div
          className="graph-coordinate-viewport"
          ref={graphViewportRef}
          style={{ height: graphViewportHeight }}
          onWheel={handleGraphWheel}
          onPointerDownCapture={handleGraphPointerDownCapture}
          onPointerMoveCapture={handleGraphPointerMoveCapture}
          onPointerUpCapture={handleGraphPointerUpCapture}
          onPointerCancelCapture={handleGraphPointerUpCapture}
        >
        <div className="graph-coordinate-world" ref={graphWorldRef}>
        <div
          className="teacher-grid"
          onPointerDown={handlePointerDown}
          onPointerMove={moveDrag}
          onPointerUp={endDrag}
          onPointerCancel={endDrag}
          onLostPointerCapture={endDrag}
        >
          <TeacherBranch
            teacher={teacherGraph?.teacher || profile}
            students={teacherGraph?.students || []}
            studentLayout={teacherStudentLayout}
            isOwner
          />
        </div>
        </div>
        </div>
      </section>}

      {profile?.role === "admin" && <section className="graph-panel">
        <div className="graph-legend-row">
          <div className="legend graph-legend">
            <div className="graph-legend-item"><span className="teacher-dot" />Учителя <b>{overview?.counts.teachers || 0}</b></div>
            <div className="graph-legend-item"><span className="student-dot" />Ученики <b>{overview?.counts.students || 0}</b></div>
          </div>
          <div className="graph-toolbar-actions">
            <button className="btn primary graph-add-participant" onClick={() => openCreate()}><Plus />Добавить участника</button>
          </div>
        </div>
        <div
          className="graph-coordinate-viewport"
          ref={graphViewportRef}
          style={{ height: graphViewportHeight }}
          onWheel={handleGraphWheel}
          onPointerDownCapture={handleGraphPointerDownCapture}
          onPointerMoveCapture={handleGraphPointerMoveCapture}
          onPointerUpCapture={handleGraphPointerUpCapture}
          onPointerCancelCapture={handleGraphPointerUpCapture}
        >
        <div className="graph-coordinate-world" ref={graphWorldRef}>
        <div className="root-node"><img src="/logo.png" alt="" /><b>Администратор</b><small>Полное управление</small></div>

        {!!unassignedStudents.length && <section className="unassigned">
          <div
            className="unassigned-grid"
            onPointerDown={handlePointerDown}
            onPointerMove={moveDrag}
            onPointerUp={endDrag}
            onPointerCancel={endDrag}
            onLostPointerCapture={endDrag}
          >{unassignedStudents.map(student => <div
            className="person-card student-card unassigned-student-card"
            key={student.id}
            style={positionStyle(studentLayout[student.id])}
            data-drag-type="student"
            data-drag-id={student.id}
          >
            <div className="person-main"><div className="avatar student-avatar"><Smile /></div><div className="person-info"><b>{student.full_name}</b>{student.additional_info && <small className="student-additional-info">{student.additional_info}</small>}</div></div>
            <div className="unassigned-student-actions">
              <button type="button" className="icon-btn graph-person-action" title="Редактировать" onClick={() => openEdit(student)}><Pencil /></button>
              <button className="btn small outline" disabled={!allTeachers.length} onClick={() => { setStudentId(String(student.id)); setTeacherId(String(allTeachers[0]?.id || "")); setModal({ mode: "assign" }); }}>Назначить</button>
            </div>
          </div>)}</div>
        </section>}

        <div
          className="teacher-grid"
          onPointerDown={handlePointerDown}
          onPointerMove={moveDrag}
          onPointerUp={endDrag}
          onPointerCancel={endDrag}
          onLostPointerCapture={endDrag}
        >
          {allTeachers.map(teacher => <TeacherBranch
            key={teacher.id}
            teacher={teacher}
            students={studentsByTeacherId.get(teacher.id) || []}
            studentLayout={studentLayout}
            studentsCollapsed={collapsedTeacherIds.has(teacher.id)}
            cloudLayout={cloudLayout}
            cloudStack={cloudStack}
            setCollapsedTeacherIds={setCollapsedTeacherIds}
            openEdit={openEdit}
            setTeacherId={setTeacherId}
            setStudentId={setStudentId}
            allStudents={allStudents}
            setModal={setModal}
            unassignStudent={unassignStudent}
          />)}
        </div>
        {!allTeachers.length && <div className="empty-state"><GraduationCap /><b>Пока нет учителей</b><span>Добавьте первого учителя, затем учеников и связи между ними.</span></div>}
        </div>
        </div>
      </section>}
    </>
  );
}
