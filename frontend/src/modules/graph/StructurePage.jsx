import { useLayoutEffect, useRef } from "react";
import Crosshair from "lucide-react/dist/esm/icons/crosshair.js";
import GraduationCap from "lucide-react/dist/esm/icons/graduation-cap.js";
import Link2Off from "lucide-react/dist/esm/icons/link-2-off.js";
import Pencil from "lucide-react/dist/esm/icons/pencil.js";
import Plus from "lucide-react/dist/esm/icons/plus.js";
import Smile from "lucide-react/dist/esm/icons/smile.js";
import Trash2 from "lucide-react/dist/esm/icons/trash-2.js";

function objectPosition(item) {
  return { transform: `translate3d(${item?.x || 0}px, ${item?.y || 0}px, 0)` };
}

function StudentCard({ student, openEdit, unassignStudent, canUnassign = true }) {
  return <article className="person-card student-card">
    <div className="person-main">
      <div className="avatar student-avatar"><Smile /></div>
      <div className="person-info">
        <b>{student.full_name}</b>
        {student.additional_info && <small className="student-additional-info">{student.additional_info}</small>}
      </div>
    </div>
    <div className="person-actions">
      {canUnassign && <button type="button" className="icon-btn graph-person-action" title="Открепить от учителя" aria-label={`Открепить ${student.full_name} от учителя`} onClick={() => unassignStudent(student)}><Link2Off /></button>}
      <button type="button" className="icon-btn graph-person-action" title="Редактировать" onClick={() => openEdit(student)}><Pencil /></button>
    </div>
  </article>;
}

function TeacherObject({ teacher, students, openEdit, unassignStudent, canUnassign = true }) {
  return <section className="graph-teacher-object">
    <header className="person-card teacher-card">
      <div className="person-main">
        <div className="avatar teacher-avatar"><GraduationCap /></div>
        <div className="person-info"><b>{teacher.full_name}</b><small>Учитель · {students.length} учен.</small></div>
      </div>
      <div className="person-actions">
        <button type="button" title="Редактировать" onClick={() => openEdit(teacher)}><Pencil /></button>
      </div>
    </header>
    <div className="graph-student-children">
      {students.map(student => <StudentCard key={student.id} student={student} openEdit={openEdit} unassignStudent={unassignStudent} canUnassign={canUnassign} />)}
      {!students.length && <div className="empty-students">Нет назначенных учеников</div>}
    </div>
  </section>;
}

export default function StructurePage({
  profile, teacherGraph, graphObjects = [], allTeachers = [], studentsByTeacherId,
  unassignedStudents = [], openEdit, unassignStudent, openCreate, createGraphObject,
  saveGraphObjectPosition, deleteGraphObject,
}) {
  const viewportRef = useRef(null);
  const worldRef = useRef(null);
  const dragRef = useRef(null);
  const frameRef = useRef(0);
  const transformRef = useRef({ zoom: 1, x: 0, y: 0 });
  const objectMap = new Map(graphObjects.map(item => [item.key, item]));
  const fon = objectMap.get("fon");
  const admin = objectMap.get("administrator");
  const assignedArea = objectMap.get("assigned_students");
  const teachersArea = objectMap.get("teachers");
  const customObjects = graphObjects.filter(item => item.type === "object" || item.key.startsWith("custom:"));

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
    const handle = event.target.closest(".graph-object-header, .graph-custom-object");
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

  function addObject(parentId) {
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

  if (profile?.role === "teacher") {
    const teacher = teacherGraph?.teacher || profile;
    const students = teacherGraph?.students || [];
    return <section className="graph-panel is-teacher-view">
      <div className="graph-panel-heading"><b>Моя структура</b></div>
      <div className="graph-teacher-view">
        <TeacherObject teacher={teacher} students={students} openEdit={openEdit} unassignStudent={unassignStudent} canUnassign={false} />
      </div>
    </section>;
  }

  return <section className="graph-panel graph-object-panel">
    <div className="graph-legend-row">
      <div className="graph-legend"><b>Иерархия объектов</b><span>Перемещайте Fon и облачко администратора независимо.</span></div>
      <div className="graph-toolbar-actions">
        <button type="button" className="btn small outline" onClick={resetView} title="Сбросить масштаб"><Crosshair />Сбросить масштаб</button>
        <button type="button" className="btn primary graph-add-participant" onClick={() => openCreate()}><Plus />Добавить участника</button>
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
        {fon && <div className="graph-object-fon" data-object-id={fon.id} style={objectPosition(fon)}>
          <header className="graph-object-header graph-fon-header">
            <b>Fon</b><span>Главный фон · родитель всех объектов</span>
            <button type="button" className="btn small outline" onClick={() => addObject(fon.id)}><Plus />Создать объект</button>
            <button type="button" className="graph-object-delete" title="Удалить Fon" aria-label="Удалить Fon" onClick={() => removeObject(fon)}><Trash2 /></button>
          </header>
          {admin && <section className="graph-object-admin" data-object-id={admin.id} style={objectPosition(admin)}>
            <header className="graph-object-header graph-admin-header">
              <div className="graph-admin-identity"><img src="/logo.png" alt="" /><div><b>Администратор</b><span>Родитель областей и их содержимого</span></div></div>
              <button type="button" className="btn small outline" onClick={() => addObject(admin.id)}><Plus />Создать объект</button>
              <button type="button" className="graph-object-delete" title="Удалить администратора" aria-label="Удалить администратора" onClick={() => removeObject(admin)}><Trash2 /></button>
            </header>
            <div className="graph-admin-areas">
              <section className="graph-object-area graph-assigned-area" data-object-id={assignedArea?.id}>
                <header className="graph-area-header"><b>{assignedArea?.title || "Назначенные ученики"}</b><span>{unassignedStudents.length} учен.</span>{assignedArea && <button type="button" className="graph-object-delete" title="Удалить область" aria-label="Удалить область назначенных учеников" onClick={() => removeObject(assignedArea)}><Trash2 /></button>}</header>
                <div className="graph-area-content graph-student-grid">
                  {unassignedStudents.map(student => <StudentCard key={student.id} student={student} openEdit={openEdit} canUnassign={false} />)}
                  {!unassignedStudents.length && <div className="empty-students">Нет учеников без назначения учителю</div>}
                </div>
              </section>
              <section className="graph-object-area graph-teachers-area" data-object-id={teachersArea?.id}>
                <header className="graph-area-header"><b>{teachersArea?.title || "Учителя"}</b><span>{allTeachers.length}</span>{teachersArea && <button type="button" className="graph-object-delete" title="Удалить область" aria-label="Удалить область учителей" onClick={() => removeObject(teachersArea)}><Trash2 /></button>}</header>
                <div className="graph-area-content graph-teachers-grid">
                  {allTeachers.map(teacher => <TeacherObject key={teacher.id} teacher={teacher} students={studentsByTeacherId?.get(teacher.id) || []} openEdit={openEdit} unassignStudent={unassignStudent} />)}
                  {!allTeachers.length && <div className="empty-students">Пока нет учителей</div>}
                </div>
              </section>
            </div>
            {customObjects.filter(item => item.parent_id === admin.id).map(item => <div key={item.id} className="graph-custom-object" data-object-id={item.id} style={objectPosition(item)}><span>{item.title}</span><button type="button" className="graph-object-delete" title={`Удалить объект «${item.title}»`} aria-label={`Удалить объект «${item.title}»`} onClick={() => removeObject(item)}><Trash2 /></button></div>)}
          </section>}
          {customObjects.filter(item => item.parent_id === fon.id).map(item => <div key={item.id} className="graph-custom-object" data-object-id={item.id} style={objectPosition(item)}><span>{item.title}</span><button type="button" className="graph-object-delete" title={`Удалить объект «${item.title}»`} aria-label={`Удалить объект «${item.title}»`} onClick={() => removeObject(item)}><Trash2 /></button></div>)}
        </div>}
      </div>
    </div>
  </section>;
}
