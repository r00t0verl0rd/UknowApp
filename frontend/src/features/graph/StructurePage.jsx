import { useState } from "react";
import ChevronRight from "lucide-react/dist/esm/icons/chevron-right.js";
import GraduationCap from "lucide-react/dist/esm/icons/graduation-cap.js";
import Pencil from "lucide-react/dist/esm/icons/pencil.js";
import Plus from "lucide-react/dist/esm/icons/plus.js";
import Smile from "lucide-react/dist/esm/icons/smile.js";
import Unlink from "lucide-react/dist/esm/icons/unlink.js";
import EmptyState from "../../shared/components/EmptyState.jsx";
import CountBadge from "../../shared/components/CountBadge.jsx";
import Button from "../../shared/components/Button.jsx";
import IconButton from "../../shared/components/IconButton.jsx";

export default function StructurePage({
  overview, loading, openCreate, allTeachers = [],
  studentsByTeacherId = new Map(), openEdit, setTeacherId, setStudentId,
  allStudents = [], setModal, unassignedStudents = [], unassignStudent,
}) {
  const [collapsedTeacherIds, setCollapsedTeacherIds] = useState(() => new Set());
  return <>
    <div className="graph-legend-row">
      <div className="legend graph-legend">
        <div className="graph-legend-item"><span className="teacher-dot" />Учителя <CountBadge as="b" value={overview?.counts?.teachers || 0} label="учителей"/></div>
        <div className="graph-legend-item"><span className="student-dot" />Ученики <CountBadge as="b" value={overview?.counts?.students || 0} label="учеников"/></div>
      </div>
      <Button type="button" variant="primary" className="graph-add-participant" onClick={() => openCreate()}><Plus />Добавить участника</Button>
    </div>
    <div className="role_node"><img src="/logo.png" alt="" /><div><b>Администратор</b><small>Полное управление</small></div></div>
    <div className="grid">
      {allTeachers.map(teacher => {
        const students = studentsByTeacherId.get(teacher.id) || [];
        const collapsed = collapsedTeacherIds.has(teacher.id);
        return <section className={`teacher-branch${collapsed ? " is-collapsed" : ""}`} key={teacher.id}>
          <div className="teacher-card">
            <div className="person-main"><div className="avatar teacher-avatar"><GraduationCap /></div><div className="person-info"><b>{teacher.full_name}</b><small>Учитель · {students.length} учен.</small></div></div>
            <div className="person-actions">
              <IconButton tone="danger" className={`danger-icon teacher-collapse-btn${collapsed ? "" : " is-expanded"}`} title={collapsed ? "Показать учеников" : "Скрыть учеников"} aria-label={collapsed ? "Показать учеников" : "Скрыть учеников"} aria-expanded={!collapsed} onClick={() => setCollapsedTeacherIds(current => {
                const next = new Set(current);
                if (next.has(teacher.id)) next.delete(teacher.id);
                else next.add(teacher.id);
                return next;
              })}><ChevronRight /></IconButton>
              <IconButton title="Редактировать преподавателя" aria-label={`Редактировать преподавателя ${teacher.full_name}`} onClick={() => openEdit(teacher)}><Pencil /></IconButton>
            </div>
          </div>
          {!collapsed && <button type="button" className="add-student" onClick={() => {
            setTeacherId(String(teacher.id));
            setStudentId(allStudents[0]?.id ? String(allStudents[0].id) : "");
            setModal({ mode: "assign" });
          }}><Plus />Назначить ученика</button>}
          {!collapsed && <div className="student-list">
            {students.map(student => <div className="student-card" key={student.id}>
              <div className="person-main"><div className="avatar student-avatar"><Smile /></div><div className="person-info"><b>{student.full_name}</b>{student.additional_info && <small className="student-additional-info">{student.additional_info}</small>}</div></div>
              <IconButton className="graph-person-action" title="Редактировать ученика" aria-label={`Редактировать ученика ${student.full_name}`} onClick={() => openEdit(student)}><Pencil /></IconButton>
              <IconButton className="graph-person-action" title="Отвязать от учителя" aria-label={"Отвязать ученика " + student.full_name + " от учителя"} onClick={() => unassignStudent(student)}><Unlink /></IconButton>
            </div>)}
            {!students.length && <div className="empty-students">Нет назначенных учеников</div>}
          </div>}
        </section>;
      })}
    </div>
    {!loading && !allTeachers.length && <EmptyState><GraduationCap /><b>Пока нет учителей</b><span>Добавьте первого учителя, затем учеников и связи между ними.</span></EmptyState>}
    {!!unassignedStudents.length && <section className="unassigned">
      <h2 className="unassigned-title">Ученики без учителя</h2>
      <div className="unassigned-grid">{unassignedStudents.map(student => <div className="student-card unassigned-student-card" key={student.id}>
        <div className="person-main"><div className="avatar student-avatar"><Smile /></div><div className="person-info"><b>{student.full_name}</b>{student.additional_info && <small className="student-additional-info">{student.additional_info}</small>}</div></div>
        <div className="unassigned-student-actions">
          <IconButton className="graph-person-action" title="Редактировать ученика" aria-label={`Редактировать ученика ${student.full_name}`} onClick={() => openEdit(student)}><Pencil /></IconButton>
          <Button type="button" size="small" variant="outline" disabled={!allTeachers.length} onClick={() => {
            setStudentId(String(student.id));
            setTeacherId(String(allTeachers[0]?.id || ""));
            setModal({ mode: "assign" });
          }}>Назначить</Button>
        </div>
      </div>)}</div>
    </section>}
  </>;
}
