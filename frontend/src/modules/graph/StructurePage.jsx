import { useEffect, useLayoutEffect, useRef, useState } from "react";
import ChevronRight from "lucide-react/dist/esm/icons/chevron-right.js";
import GraduationCap from "lucide-react/dist/esm/icons/graduation-cap.js";
import Link2Off from "lucide-react/dist/esm/icons/link-2-off.js";
import Pencil from "lucide-react/dist/esm/icons/pencil.js";
import Plus from "lucide-react/dist/esm/icons/plus.js";
import Smile from "lucide-react/dist/esm/icons/smile.js";

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

function snapToGrid(value) {
  return Math.round(value / GRAPH_GRID_SIZE) * GRAPH_GRID_SIZE;
}

function findFreeGridPosition(element, siblings, currentPosition) {
  const parent = element.parentElement;
  const bounds = parent.getBoundingClientRect();
  const rect = element.getBoundingClientRect();
  const maxX = Math.max(0, bounds.right - rect.right + currentPosition.x);
  const collides = (candidateX, candidateY) => {
    const left = rect.left + candidateX - currentPosition.x;
    const top = rect.top + candidateY - currentPosition.y;
    const right = left + rect.width;
    const bottom = top + rect.height;
    if (left < bounds.left - 1 || top < bounds.top - 1 || right > bounds.right + 1) return true;
    return siblings.some(other => {
      if (other === element) return false;
      const otherRect = other.getBoundingClientRect();
      return left < otherRect.right - 1 && right > otherRect.left + 1 && top < otherRect.bottom - 1 && bottom > otherRect.top + 1;
    });
  };

  if (!collides(currentPosition.x, currentPosition.y)) return currentPosition;
  const maxSteps = Math.ceil(Math.max(bounds.width, bounds.height, 1200) / GRAPH_GRID_SIZE);
  for (let radius = 1; radius <= maxSteps; radius += 1) {
    for (let step = -radius; step <= radius; step += 1) {
      const candidates = [
        [step, -radius], [step, radius], [-radius, step], [radius, step],
      ];
      for (const [column, row] of candidates) {
        const x = currentPosition.x + column * GRAPH_GRID_SIZE;
        const y = currentPosition.y + row * GRAPH_GRID_SIZE;
        if (x < 0 || y < 0 || x > maxX) continue;
        if (!collides(x, y)) return { x, y };
      }
    }
  }
  return currentPosition;
}

function dragPosition(drag, clientX, clientY) {
  const bounds = drag.boundaryRect;
  const element = drag.elementRect;
  const clamp = (value, min, max) => min > max ? (min + max) / 2 : Math.max(min, Math.min(max, value));
  const dx = clamp(clientX - drag.startX, bounds.left - element.left, bounds.right - element.right);
  const dy = clamp(clientY - drag.startY, bounds.top - element.top, bounds.bottom - element.bottom);
  return {
    x: clamp(snapToGrid(drag.x + dx), drag.x + bounds.left - element.left, drag.x + bounds.right - element.right),
    y: clamp(snapToGrid(drag.y + dy), drag.y + bounds.top - element.top, drag.y + bounds.bottom - element.bottom),
  };
}

function TeacherBranch({ teacher, students, studentLayout, studentsCollapsed = false, isOwner = false, cloudLayout, cloudStack, setCollapsedTeacherIds, openEdit, setTeacherId, setStudentId, allStudents, setModal, unassignStudent }) {
  return (
    <section
      className={`teacher-branch${studentsCollapsed ? " is-collapsed" : ""}`}
      key={teacher.id}
      style={isOwner ? undefined : { ...positionStyle(cloudLayout[teacher.id]), zIndex: cloudStack[teacher.id] || 0 }}
    >
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
    </section>
  );
}

export default function StructurePage({ profile, teacherGraph, overview, openCreate, allTeachers, studentsByTeacherId, collapsedTeacherIds, setCollapsedTeacherIds, openEdit, setTeacherId, setStudentId, allStudents, setModal, unassignedStudents, unassignStudent, saveCloudPosition }) {
  const cloudPositions = overview?.cloud_positions || EMPTY_CLOUD_POSITIONS;
  const [cloudLayout, setCloudLayout] = useState(() => positionMap(cloudPositions));
  const cloudLayoutRef = useRef(cloudLayout);
  const [cloudStack, setCloudStack] = useState({});
  const cloudStackRef = useRef(0);
  const [studentLayout, setStudentLayout] = useState(readStudentLayout);
  const studentLayoutRef = useRef(studentLayout);
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

  useEffect(() => {
    const next = positionMap(cloudPositions);
    cloudLayoutRef.current = next;
    setCloudLayout(next);
  }, [cloudPositions]);

  useLayoutEffect(() => {
    const isAdmin = profile?.role === "admin";
    const isTeacher = profile?.role === "teacher";
    if (!isAdmin && !isTeacher) return;

    const nextClouds = { ...cloudLayoutRef.current };
    const nextStudents = { ...studentLayoutRef.current };
    const nextTeacherStudents = { ...teacherStudentLayoutRef.current };
    let cloudsChanged = false;
    let studentsChanged = false;
    let teacherStudentsChanged = false;

    const allocateGroup = (selector, layout, onAllocate) => {
      const elements = [...document.querySelectorAll(selector)];
      elements.forEach(element => {
        const id = element.dataset.dragId;
        if (!id || layout[id]) return;
        const siblings = elements.filter(other => other !== element);
        const position = findFreeGridPosition(element, siblings, { x: 0, y: 0 });
        if (position.x || position.y) {
          element.style.transform = `translate3d(${position.x}px, ${position.y}px, 0)`;
          const parent = element.parentElement;
          const bounds = parent.getBoundingClientRect();
          const rect = element.getBoundingClientRect();
          const requiredHeight = rect.bottom - bounds.top;
          parent.style.minHeight = `${Math.max(parent.scrollHeight, requiredHeight)}px`;
          layout[id] = position;
          onAllocate(position, id);
        }
      });
    };

    if (isAdmin) {
      allocateGroup(".graph-panel:not(.is-teacher-view) > .teacher-grid > .teacher-branch", nextClouds, (position, id) => {
        cloudsChanged = true;
        saveCloudPosition(id, position.x, position.y);
      });
      allocateGroup(".graph-panel:not(.is-teacher-view) .student-list > .student-card", nextStudents, () => { studentsChanged = true; });
      allocateGroup(".graph-panel:not(.is-teacher-view) .unassigned-grid > .student-card", nextStudents, () => { studentsChanged = true; });
    } else {
      allocateGroup(".graph-panel.is-teacher-view .student-list > .student-card", nextTeacherStudents, () => { teacherStudentsChanged = true; });
    }

    if (cloudsChanged) {
      cloudLayoutRef.current = nextClouds;
      setCloudLayout(nextClouds);
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

  function startDrag(event, handle) {
    if (event.button !== 0 || event.target.closest("button, a, input, select, textarea")) return;
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
    const bounded = type === "student";
    dragRef.current = {
      type, id, element, teacherView, pointerId: event.pointerId,
      startX: event.clientX, startY: event.clientY,
      x: position.x, y: position.y,
      nextX: position.x, nextY: position.y,
      ...(bounded ? {
        boundaryRect: element.parentElement.getBoundingClientRect(),
        elementRect: element.getBoundingClientRect(),
      } : {}),
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
    const position = drag.type === "student"
      ? dragPosition(drag, event.clientX, event.clientY)
      : { x: snapToGrid(drag.x + event.clientX - drag.startX), y: snapToGrid(drag.y + event.clientY - drag.startY) };
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
    let { x, y } = drag.type === "student"
      ? dragPosition(drag, event.clientX, event.clientY)
      : { x: snapToGrid(drag.x + event.clientX - drag.startX), y: snapToGrid(drag.y + event.clientY - drag.startY) };
    const hit = document.elementFromPoint(event.clientX, event.clientY)?.closest("[data-drag-type]");
    const target = drag.type === "cloud" ? hit?.closest(".teacher-branch") : hit;
    const targetId = hit?.dataset.dragId;
    const targetType = hit?.dataset.dragType;
    const sameGroup = target && target !== drag.element && target.parentElement === drag.element.parentElement;
    const canSwap = sameGroup && targetType === drag.type && targetId;
    const swapTarget = canSwap ? target : null;
    let targetPosition = null;
    drag.element.style.transform = `translate3d(${x}px, ${y}px, 0)`;
    if (swapTarget) {
      const currentRect = drag.element.getBoundingClientRect();
      const targetRect = target.getBoundingClientRect();
      const dx = targetRect.left - currentRect.left;
      const dy = targetRect.top - currentRect.top;
      const layout = drag.type === "cloud" ? cloudLayoutRef.current : drag.teacherView ? teacherStudentLayoutRef.current : studentLayoutRef.current;
      const previousTarget = layout[targetId] || { x: 0, y: 0 };
      targetPosition = { id: targetId, x: previousTarget.x - dx, y: previousTarget.y - dy };
      x += dx;
      y += dy;
    }
    drag.element.style.transform = `translate3d(${x}px, ${y}px, 0)`;
    if (swapTarget && targetPosition) {
      swapTarget.style.transform = `translate3d(${targetPosition.x}px, ${targetPosition.y}px, 0)`;
    }
    drag.element.classList.remove("is-dragging");
    drag.element.style.willChange = "";
    drag.element.style.transition = "";
    dragRef.current = null;
    if (Math.abs(x - drag.x) < 1 && Math.abs(y - drag.y) < 1) return;

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
  }, []);

  return (
    <>
      {profile?.role === "teacher" && <section className="graph-panel is-teacher-view">
        <div
          className="teacher-grid"
          onPointerDown={handlePointerDown}
          onPointerMove={moveDrag}
          onPointerUp={endDrag}
          onPointerCancel={endDrag}
        >
          <TeacherBranch
            teacher={teacherGraph?.teacher || profile}
            students={teacherGraph?.students || []}
            studentLayout={teacherStudentLayout}
            isOwner
          />
        </div>
      </section>}

      {profile?.role === "admin" && <section className="graph-panel">
        <div className="graph-legend-row">
          <div className="legend graph-legend">
            <div className="graph-legend-item"><span className="teacher-dot" />Учителя <b>{overview?.counts.teachers || 0}</b></div>
            <div className="graph-legend-item"><span className="student-dot" />Ученики <b>{overview?.counts.students || 0}</b></div>
          </div>
          <button className="btn primary graph-add-participant" onClick={() => openCreate()}><Plus />Добавить участника</button>
        </div>
        <div className="root-node"><img src="/logo.png" alt="" /><b>Администратор</b><small>Полное управление</small></div>

        {!!unassignedStudents.length && <section className="unassigned">
          <div
            className="unassigned-grid"
            onPointerDown={handlePointerDown}
            onPointerMove={moveDrag}
            onPointerUp={endDrag}
            onPointerCancel={endDrag}
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
      </section>}
    </>
  );
}
