import { useEffect, useRef, useState } from "react";
import ChevronRight from "lucide-react/dist/esm/icons/chevron-right.js";
import GraduationCap from "lucide-react/dist/esm/icons/graduation-cap.js";
import Link2Off from "lucide-react/dist/esm/icons/link-2-off.js";
import Pencil from "lucide-react/dist/esm/icons/pencil.js";
import Plus from "lucide-react/dist/esm/icons/plus.js";
import Smile from "lucide-react/dist/esm/icons/smile.js";

function orderedItems(items, order) {
  const byId = new Map(items.map(item => [item.id, item]));
  return [...order.map(id => byId.get(id)).filter(Boolean), ...items.filter(item => !order.includes(item.id))];
}

function moveItem(order, sourceId, targetId, after) {
  const next = order.filter(id => id !== sourceId);
  const targetIndex = next.indexOf(targetId);
  next.splice(targetIndex < 0 ? next.length : targetIndex + Number(after), 0, sourceId);
  return next;
}

export default function StructurePage({ profile, teacherGraph, overview, openCreate, allTeachers, studentsByTeacherId, collapsedTeacherIds, setCollapsedTeacherIds, openEdit, setTeacherId, setStudentId, allStudents, setModal, unassignedStudents, unassignStudent, saveGraphOrder }) {
  const [teacherOrder, setTeacherOrder] = useState(() => allTeachers.map(item => item.id));
  const [studentOrders, setStudentOrders] = useState({});
  const [unassignedOrder, setUnassignedOrder] = useState(() => unassignedStudents.map(item => item.id));
  const dragRef = useRef(null);

  useEffect(() => {
    setTeacherOrder(allTeachers.map(item => item.id));
    setStudentOrders(Object.fromEntries(allTeachers.map(teacher => [
      teacher.id,
      (studentsByTeacherId.get(teacher.id) || []).map(student => student.id),
    ])));
    setUnassignedOrder(unassignedStudents.map(item => item.id));
  }, [allTeachers, studentsByTeacherId, unassignedStudents]);

  function beginDrag(event, group, id, order) {
    if (event.button !== 0 || event.target.closest("button, a, input, select, textarea")) return;
    dragRef.current = { group, id, pointerId: event.pointerId, order: [...order], changed: false, target: null };
    event.currentTarget.setPointerCapture(event.pointerId);
    event.currentTarget.classList.add("is-dragging");
  }

  function moveDrag(event) {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    const target = document.elementFromPoint(event.clientX, event.clientY)?.closest("[data-sort-group][data-sort-id]");
    if (!target || target.dataset.sortGroup !== drag.group) {
      drag.target?.classList.remove("is-drop-target");
      drag.target = null;
      return;
    }
    if (target.dataset.sortId === String(drag.id)) return;
    drag.target?.classList.remove("is-drop-target");
    drag.target = target;
    target.classList.add("is-drop-target");
    const bounds = target.getBoundingClientRect();
    const horizontal = bounds.width > bounds.height;
    const after = horizontal
      ? event.clientX > bounds.left + bounds.width / 2
      : event.clientY > bounds.top + bounds.height / 2;
    const next = moveItem(drag.order, drag.id, Number(target.dataset.sortId), after);
    if (next.every((id, index) => id === drag.order[index])) return;
    drag.order = next;
    drag.changed = true;
    if (drag.group === "teachers") setTeacherOrder(next);
    else if (drag.group === "unassigned") setUnassignedOrder(next);
    else {
      const teacherId = Number(drag.group.slice("students:".length));
      setStudentOrders(current => ({ ...current, [teacherId]: next }));
    }
  }

  function finishDrag(event) {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    drag.target?.classList.remove("is-drop-target");
    event.currentTarget.classList.remove("is-dragging");
    dragRef.current = null;
    if (drag.changed) void saveGraphOrder(drag.group, drag.order);
  }

  const dragHandlers = (group, id, order) => ({
    "data-sort-group": group,
    "data-sort-id": String(id),
    onPointerDown: event => beginDrag(event, group, id, order),
    onPointerMove: moveDrag,
    onPointerUp: finishDrag,
    onPointerCancel: finishDrag,
  });

  return (
    <>
      {profile?.role === "teacher" && <section className="teacher-readonly-graph">
        <div className="teacher-graph-root">
          <div className="teacher-graph-card">
            <div className="avatar teacher-avatar"><GraduationCap/></div>
            <div><b>{teacherGraph?.teacher.full_name || profile?.full_name}</b><small>Вы · Учитель</small></div>
            <span className="readonly-tag">Ваша группа</span>
          </div>
          <div className="teacher-graph-students">
            <div className="teacher-graph-student-grid">
              {(teacherGraph?.students || []).map(student => <div className="teacher-graph-card student" key={student.id}>
                <div className="avatar student-avatar"><Smile/></div>
                <div><b>{student.full_name}</b>{student.additional_info && <small className="student-additional-info">{student.additional_info}</small>}</div>
              </div>)}
            </div>
            {!(teacherGraph?.students || []).length && <div className="empty-state">Пока нет назначенных учеников</div>}
          </div>
        </div>
      </section>}
      {profile?.role === "admin" && <section className="graph-panel">
        <div className="graph-legend-row">
          <div className="legend graph-legend">
            <div className="graph-legend-item"><span className="teacher-dot"/>Учителя <b>{overview?.counts.teachers || 0}</b></div>
            <div className="graph-legend-item"><span className="student-dot"/>Ученики <b>{overview?.counts.students || 0}</b></div>
          </div>
          <button className="btn primary graph-add-participant" onClick={() => openCreate()}><Plus/>Добавить участника</button>
        </div>
        <div className="root-node"><img src="/logo.png" alt=""/><div><b>Администратор</b><small>Полное управление</small></div></div>
        {!!unassignedStudents.length && <section className="unassigned">
          <div className="unassigned-grid">
            {orderedItems(unassignedStudents, unassignedOrder).map(student => <div className="person-card student-card unassigned-student-card" key={student.id} {...dragHandlers("unassigned", student.id, unassignedOrder)}>
              <div className="person-main"><div className="avatar student-avatar"><Smile/></div><div className="person-info"><b>{student.full_name}</b>{student.additional_info && <small className="student-additional-info">{student.additional_info}</small>}</div></div>
              <div className="unassigned-student-actions">
                <button type="button" className="icon-btn graph-person-action" title="Редактировать" onClick={() => openEdit(student)}><Pencil/></button>
                <button className="btn small outline" disabled={!allTeachers.length} onClick={() => { setStudentId(String(student.id)); setTeacherId(String(allTeachers[0]?.id || "")); setModal({ mode: "assign" }); }}>Назначить</button>
              </div>
            </div>)}
          </div>
        </section>}
        <div className="teacher-grid">
          {orderedItems(allTeachers, teacherOrder).map(teacher => {
            const students = studentsByTeacherId.get(teacher.id) || [];
            const order = studentOrders[teacher.id] || students.map(student => student.id);
            const studentsCollapsed = collapsedTeacherIds.has(teacher.id);
            return <section className={`teacher-branch${studentsCollapsed ? " is-collapsed" : ""}`} key={teacher.id}>
              <div className="person-card teacher-card" {...dragHandlers("teachers", teacher.id, teacherOrder)}>
                <div className="person-main"><div className="avatar teacher-avatar"><GraduationCap/></div><div className="person-info"><b>{teacher.full_name}</b><small>Учитель · {students.length} учен.</small></div></div>
                <div className="person-actions">
                  <button className={`danger-icon teacher-collapse-btn${studentsCollapsed ? "" : " is-expanded"}`} title={studentsCollapsed ? "Показать учеников" : "Скрыть учеников"} aria-label={studentsCollapsed ? "Показать учеников" : "Скрыть учеников"} aria-expanded={!studentsCollapsed} onClick={() => setCollapsedTeacherIds(current => { const next = new Set(current); if (next.has(teacher.id)) next.delete(teacher.id); else next.add(teacher.id); return next; })}><ChevronRight/></button>
                  <button title="Редактировать" onClick={() => openEdit(teacher)}><Pencil/></button>
                </div>
              </div>
              {!studentsCollapsed && <button className="add-student" onClick={() => { setTeacherId(String(teacher.id)); setStudentId(allStudents[0]?.id ? String(allStudents[0].id) : ""); setModal({ mode: "assign" }); }}><Plus/>Назначить ученика</button>}
              {!studentsCollapsed && <div className="student-list">
                {orderedItems(students, order).map(student => <div className="person-card student-card" key={student.id} {...dragHandlers(`students:${teacher.id}`, student.id, order)}>
                  <div className="person-main"><div className="avatar student-avatar"><Smile/></div><div className="person-info"><b>{student.full_name}</b>{student.additional_info && <small className="student-additional-info">{student.additional_info}</small>}</div></div>
                  <div className="person-actions">
                    <button type="button" className="icon-btn graph-person-action" title="Открепить от учителя" aria-label={"Открепить " + student.full_name + " от учителя"} onClick={() => unassignStudent(student)}><Link2Off/></button>
                    <button type="button" className="icon-btn graph-person-action" title="Редактировать" onClick={() => openEdit(student)}><Pencil/></button>
                  </div>
                </div>)}
                {!students.length && <div className="empty-students">Нет назначенных учеников</div>}
              </div>}
            </section>;
          })}
        </div>
        {!allTeachers.length && <div className="empty-state"><GraduationCap/><b>Пока нет учителей</b><span>Добавьте первого учителя, затем учеников и связи между ними.</span></div>}
      </section>}
    </>
  );
}
