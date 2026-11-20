import ChevronRight from "lucide-react/dist/esm/icons/chevron-right.js";
import GraduationCap from "lucide-react/dist/esm/icons/graduation-cap.js";
import Pencil from "lucide-react/dist/esm/icons/pencil.js";
import Plus from "lucide-react/dist/esm/icons/plus.js";
import Smile from "lucide-react/dist/esm/icons/smile.js";

export default function StructurePage({ profile, teacherGraph, overview, openCreate, allTeachers, studentsByTeacherId, collapsedTeacherIds, setCollapsedTeacherIds, openEdit, setTeacherId, setStudentId, allStudents, setModal, unassignedStudents }) {
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
                  <div className="teacher-graph-connector"/>
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
            {profile?.role === "admin" && <>
              <section className="graph-panel">
                <div className="graph-legend-row">
                  <div className="legend graph-legend">
                    <div className="graph-legend-item"><span className="teacher-dot"/>Учителя <b>{overview?.counts.teachers || 0}</b></div>
                    <div className="graph-legend-item"><span className="student-dot"/>Ученики <b>{overview?.counts.students || 0}</b></div>
                  </div>
                  <button className="btn primary graph-add-participant" onClick={() => openCreate()}><Plus/>Добавить участника</button>
                </div>
                <div className="root-node"><img src="/logo.png" alt=""/><div><b>Администратор</b><small>Полное управление</small></div></div>
                {!!unassignedStudents.length && <section className="unassigned"><h2 className="unassigned-title">Ученики без назначения</h2><div className="unassigned-grid">{unassignedStudents.map(student => <div className="person-card student-card unassigned-student-card" key={student.id}>
                  <div className="person-main"><div className="avatar student-avatar"><Smile/></div><div className="person-info"><b>{student.full_name}</b>{student.additional_info && <small className="student-additional-info">{student.additional_info}</small>}</div></div>
                  <div className="unassigned-student-actions">
                    <button type="button" className="icon-btn graph-person-action" title="Редактировать" onClick={() => openEdit(student)}><Pencil/></button>
                    <button className="btn small outline" disabled={!allTeachers.length} onClick={() => { setStudentId(String(student.id)); setTeacherId(String(allTeachers[0]?.id || "")); setModal({ mode: "assign" }); }}>Назначить</button>
                  </div>
                </div>)}</div></section>}
                <div className="teacher-grid">
                  {allTeachers.map(teacher => {
                    const students = studentsByTeacherId.get(teacher.id) || [];
                    const studentsCollapsed = collapsedTeacherIds.has(teacher.id);
                    return <section className={`teacher-branch${studentsCollapsed ? " is-collapsed" : ""}`} key={teacher.id}>
                    <div className="person-card teacher-card">
                      <div className="person-main"><div className="avatar teacher-avatar"><GraduationCap/></div><div className="person-info"><b>{teacher.full_name}</b><small>Учитель · {students.length} учен.</small></div></div>
                      <div className="person-actions">
                        <button className={`danger-icon teacher-collapse-btn${studentsCollapsed ? "" : " is-expanded"}`} title={studentsCollapsed ? "Показать учеников" : "Скрыть учеников"} aria-label={studentsCollapsed ? "Показать учеников" : "Скрыть учеников"} aria-expanded={!studentsCollapsed} onClick={() => setCollapsedTeacherIds(current => { const next = new Set(current); if (next.has(teacher.id)) next.delete(teacher.id); else next.add(teacher.id); return next; })}><ChevronRight/></button>
                        <button title="Редактировать" onClick={() => openEdit(teacher)}><Pencil/></button>
                      </div>
                    </div>
                    {!studentsCollapsed && <button className="add-student" onClick={() => { setTeacherId(String(teacher.id)); setStudentId(allStudents[0]?.id ? String(allStudents[0].id) : ""); setModal({ mode: "assign" }); }}><Plus/>Назначить ученика</button>}
                    {!studentsCollapsed && <div className="student-list">
                      {students.map(student => <div className="person-card student-card" key={student.id}>
                        <div className="person-main"><div className="avatar student-avatar"><Smile/></div><div className="person-info"><b>{student.full_name}</b>{student.additional_info && <small className="student-additional-info">{student.additional_info}</small>}</div></div>
                        <button type="button" className="icon-btn graph-person-action" title="Редактировать" onClick={() => openEdit(student)}><Pencil/></button>
                      </div>)}
                      {!students.length && <div className="empty-students">Нет назначенных учеников</div>}
                    </div>}
                  </section>;
                  })}
                </div>
                {!allTeachers.length && <div className="empty-state"><GraduationCap/><b>Пока нет учителей</b><span>Добавьте первого учителя, затем учеников и связи между ними.</span></div>}
              </section>
            </>}
    </>
  );
}
