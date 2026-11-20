import GraduationCap from "lucide-react/dist/esm/icons/graduation-cap.js";
import Smile from "lucide-react/dist/esm/icons/smile.js";

export default function TeacherStructurePage({ profile, teacherGraph }) {
  const teacher = teacherGraph?.teacher || profile;
  const students = teacherGraph?.students || [];
  return <section className="graph-panel is-teacher-view">
    <div className="graph-panel-heading"><b>Моя структура</b></div>
    <section className="teacher-readonly-graph">
      <div className="teacher-graph-root">
        <div className="teacher-graph-card">
          <div className="avatar teacher-avatar"><GraduationCap /></div>
          <div><b>{teacher.full_name}</b><small>Вы · Учитель</small></div>
          <span className="readonly-tag">Ваша группа</span>
        </div>
        <div className="teacher-graph-students">
          <div className="teacher-graph-connector" />
          <div className="teacher-graph-student-grid">
            {students.map(student => <div className="teacher-graph-card student" key={student.id}>
              <div className="avatar student-avatar"><Smile /></div>
              <div><b>{student.full_name}</b>{student.additional_info && <small className="student-additional-info">{student.additional_info}</small>}</div>
            </div>)}
          </div>
          {!students.length && <div className="empty-state">Пока нет назначенных учеников</div>}
        </div>
      </div>
    </section>
  </section>;
}
