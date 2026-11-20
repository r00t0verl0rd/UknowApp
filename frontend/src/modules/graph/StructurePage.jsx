import { useEffect, useRef, useState } from "react";
import ChevronRight from "lucide-react/dist/esm/icons/chevron-right.js";
import GraduationCap from "lucide-react/dist/esm/icons/graduation-cap.js";
import Link2Off from "lucide-react/dist/esm/icons/link-2-off.js";
import Pencil from "lucide-react/dist/esm/icons/pencil.js";
import Plus from "lucide-react/dist/esm/icons/plus.js";
import Smile from "lucide-react/dist/esm/icons/smile.js";

const STUDENT_LAYOUT_KEY = "uknowapp-graph-student-layout";
const EMPTY_CLOUD_POSITIONS = [];

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

export default function StructurePage({ profile, teacherGraph, overview, openCreate, allTeachers, studentsByTeacherId, collapsedTeacherIds, setCollapsedTeacherIds, openEdit, setTeacherId, setStudentId, allStudents, setModal, unassignedStudents, unassignStudent, saveCloudPosition }) {
  const cloudPositions = overview?.cloud_positions || EMPTY_CLOUD_POSITIONS;
  const [cloudLayout, setCloudLayout] = useState(() => positionMap(cloudPositions));
  const cloudLayoutRef = useRef(cloudLayout);
  const [cloudStack, setCloudStack] = useState({});
  const cloudStackRef = useRef(0);
  const [studentLayout, setStudentLayout] = useState(readStudentLayout);
  const studentLayoutRef = useRef(studentLayout);
  const dragRef = useRef(null);
  const frameRef = useRef(0);

  useEffect(() => {
    const next = positionMap(cloudPositions);
    cloudLayoutRef.current = next;
    setCloudLayout(next);
  }, [cloudPositions]);

  function startDrag(event, handle) {
    if (event.button !== 0 || event.target.closest("button, a, input, select, textarea")) return;
    const type = handle.dataset.dragType;
    const id = handle.dataset.dragId;
    if (!type || !id) return;

    event.preventDefault();
    const captureElement = event.currentTarget;
    const element = type === "cloud" ? handle.closest(".teacher-branch") : handle;
    if (type === "cloud") element.style.zIndex = String(++cloudStackRef.current);
    const layout = type === "cloud" ? cloudLayoutRef.current : studentLayoutRef.current;
    const position = layout[id] || { x: 0, y: 0 };
    dragRef.current = {
      type, id, element, pointerId: event.pointerId,
      startX: event.clientX, startY: event.clientY,
      x: position.x, y: position.y,
      nextX: position.x, nextY: position.y,
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
    drag.nextX = drag.x + event.clientX - drag.startX;
    drag.nextY = drag.y + event.clientY - drag.startY;
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
    const x = drag.x + event.clientX - drag.startX;
    const y = drag.y + event.clientY - drag.startY;
    drag.element.style.transform = `translate3d(${x}px, ${y}px, 0)`;
    drag.element.classList.remove("is-dragging");
    drag.element.style.willChange = "";
    drag.element.style.transition = "";
    dragRef.current = null;
    if (Math.abs(x - drag.x) < 1 && Math.abs(y - drag.y) < 1) return;

    if (drag.type === "cloud") {
      const next = { ...cloudLayoutRef.current, [drag.id]: { x, y } };
      cloudLayoutRef.current = next;
      setCloudLayout(next);
      setCloudStack(current => ({ ...current, [drag.id]: cloudStackRef.current }));
      saveCloudPosition(drag.id, x, y);
      return;
    }

    const next = { ...studentLayoutRef.current, [drag.id]: { x, y } };
    studentLayoutRef.current = next;
    setStudentLayout(next);
    try {
      localStorage.setItem(STUDENT_LAYOUT_KEY, JSON.stringify(next));
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
          <section className="teacher-branch">
            <div className="person-card teacher-card">
              <div className="person-main"><div className="avatar teacher-avatar"><GraduationCap /></div><div className="person-info"><b>{teacherGraph?.teacher.full_name || profile?.full_name}</b><small>Вы · Учитель · {(teacherGraph?.students || []).length} учен.</small></div></div>
            </div>
            <div className="student-list">
              {(teacherGraph?.students || []).map(student => <div
                className="person-card student-card"
                key={student.id}
                style={positionStyle(studentLayout[student.id])}
                data-drag-type="student"
                data-drag-id={student.id}
              >
                <div className="person-main"><div className="avatar student-avatar"><Smile /></div><div className="person-info"><b>{student.full_name}</b>{student.additional_info && <small className="student-additional-info">{student.additional_info}</small>}</div></div>
              </div>)}
              {!(teacherGraph?.students || []).length && <div className="empty-students">Пока нет назначенных учеников</div>}
            </div>
          </section>
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
        <div className="root-node"><img src="/logo.png" alt="" /><div><b>Администратор</b><small>Полное управление</small></div></div>

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
          {allTeachers.map(teacher => {
            const students = studentsByTeacherId.get(teacher.id) || [];
            const studentsCollapsed = collapsedTeacherIds.has(teacher.id);
            return <section
              className={`teacher-branch${studentsCollapsed ? " is-collapsed" : ""}`}
              key={teacher.id}
              style={{ ...positionStyle(cloudLayout[teacher.id]), zIndex: cloudStack[teacher.id] || 0 }}
            >
              <div className="person-card teacher-card" data-drag-type="cloud" data-drag-id={teacher.id}>
                <div className="person-main"><div className="avatar teacher-avatar"><GraduationCap /></div><div className="person-info"><b>{teacher.full_name}</b><small>Учитель · {students.length} учен.</small></div></div>
                <div className="person-actions">
                  <button className={`danger-icon teacher-collapse-btn${studentsCollapsed ? "" : " is-expanded"}`} title={studentsCollapsed ? "Показать учеников" : "Скрыть учеников"} aria-label={studentsCollapsed ? "Показать учеников" : "Скрыть учеников"} aria-expanded={!studentsCollapsed} onClick={() => setCollapsedTeacherIds(current => { const next = new Set(current); if (next.has(teacher.id)) next.delete(teacher.id); else next.add(teacher.id); return next; })}><ChevronRight /></button>
                  <button title="Редактировать" onClick={() => openEdit(teacher)}><Pencil /></button>
                </div>
              </div>
              {!studentsCollapsed && <button className="add-student" onClick={() => { setTeacherId(String(teacher.id)); setStudentId(allStudents[0]?.id ? String(allStudents[0].id) : ""); setModal({ mode: "assign" }); }}><Plus />Назначить ученика</button>}
              {!studentsCollapsed && <div className="student-list">
                {students.map(student => <div
                  className="person-card student-card"
                  key={student.id}
                  style={positionStyle(studentLayout[student.id])}
                  data-drag-type="student"
                  data-drag-id={student.id}
                >
                  <div className="person-main"><div className="avatar student-avatar"><Smile /></div><div className="person-info"><b>{student.full_name}</b>{student.additional_info && <small className="student-additional-info">{student.additional_info}</small>}</div></div>
                  <div className="person-actions">
                    <button type="button" className="icon-btn graph-person-action" title="Открепить от учителя" aria-label={"Открепить " + student.full_name + " от учителя"} onClick={() => unassignStudent(student)}><Link2Off /></button>
                    <button type="button" className="icon-btn graph-person-action" title="Редактировать" onClick={() => openEdit(student)}><Pencil /></button>
                  </div>
                </div>)}
                {!students.length && <div className="empty-students">Нет назначенных учеников</div>}
              </div>}
            </section>;
          })}
        </div>
        {!allTeachers.length && <div className="empty-state"><GraduationCap /><b>Пока нет учителей</b><span>Добавьте первого учителя, затем учеников и связи между ними.</span></div>}
      </section>}
    </>
  );
}
