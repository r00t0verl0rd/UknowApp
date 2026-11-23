import { For } from "solid-js";
import { createSignal } from "solid-js";
import {
  IconChevronLeft as ChevronLeft,
  IconGraduationCap as GraduationCap,
  IconPencil as Pencil,
  IconPlus as Plus,
  IconSmile as Smile,
  IconUnlink as Unlink,
} from "../../shared/components/Icons.jsx";
import EmptyState from "../../shared/components/EmptyState.jsx";
import CountBadge from "../../shared/components/CountBadge.jsx";
import Button from "../../shared/components/Button.jsx";
import IconButton from "../../shared/components/IconButton.jsx";
import { viewPreference, saveViewPreference } from "../../shared/services/viewSession.js";
function StudentPerson(options) {
  return (
    <div class="person-main">
      <div class="avatar student-avatar">
        <Smile />
      </div>
      <div class="person-info">
        <b>{options.student.full_name}</b>
        {options.student.additional_info && (
          <small class="student-additional-info">{options.student.additional_info}</small>
        )}
      </div>
    </div>
  );
}

function EditStudentButton(options) {
  return (
    <IconButton
      class="graph-person-action"
      title="Редактировать ученика"
      aria-label={`Редактировать ученика ${options.student.full_name}`}
      onClick={() => options.onEdit(options.student)}
    >
      <Pencil />
    </IconButton>
  );
}

export default function StructurePage(options) {
  const [collapsedTeacherIds, setCollapsedTeacherIdsState] = createSignal(new Set(
    viewPreference(options.userId, "graph.collapsed", []),
  ));
  const setCollapsedTeacherIds = value => setCollapsedTeacherIdsState(previous => {
    const next = typeof value === "function" ? value(previous) : value;
    saveViewPreference(options.userId, "graph.collapsed", [...next]);
    return next;
  });
  return (
    <>
      <div class="graph-legend-row">
        <div class="legend graph-legend">
          <div class="graph-legend-item">
            <span class="teacher-dot" />
            Учителя <CountBadge as="b" value={options.overview?.counts?.teachers || 0} label="учителей" />
          </div>
          <div class="graph-legend-item">
            <span class="student-dot" />
            Ученики <CountBadge as="b" value={options.overview?.counts?.students || 0} label="учеников" />
          </div>
        </div>
        <Button
          type="button"
          class="graph-add-participant ui-menu-control"
          onClick={() => options.openCreate()}
        >
          <Plus />
          Добавить участника
        </Button>
      </div>
      <div class="structure-scroll" role="region" aria-label="Структура школы">
        <div class="admin-card">
          <img src="/logo-main.svg" alt="" />
          <div>
            <b>Администратор</b>
            <small>Полное управление</small>
          </div>
        </div>
        <div class="grid">
          <For each={options.allTeachers ?? []}>
            {(teacher) => {
              const students = () => (options.studentsByTeacherId ?? new Map()).get(teacher.id) || [];
              const collapsed = () => collapsedTeacherIds().has(teacher.id);
              return (
                <section data-view-anchor={"teacher:" + teacher.id} class={`teacher-branch${collapsed() ? " is-collapsed" : ""}`}>
                  <div class="teacher-card">
                    <div class="person-main">
                      <div class="avatar teacher-avatar">
                        <GraduationCap />
                      </div>
                      <div class="person-info">
                        <b>{teacher.full_name}</b>
                        <small>Учитель · {students().length} учен.</small>
                      </div>
                    </div>
                    <div class="person-actions">
                      <IconButton
                        tone="student"
                        class={`teacher-collapse-btn${collapsed() ? "" : " is-expanded"}`}
                        title={collapsed() ? "Показать учеников" : "Скрыть учеников"}
                        aria-label={collapsed() ? "Показать учеников" : "Скрыть учеников"}
                        aria-expanded={!collapsed()}
                        onClick={() =>
                          setCollapsedTeacherIds((current) => {
                            const next = new Set(current);
                            if (next.has(teacher.id)) next.delete(teacher.id);
                            else next.add(teacher.id);
                            return next;
                          })
                        }
                      >
                        <ChevronLeft />
                      </IconButton>
                      <IconButton
                        title="Редактировать преподавателя"
                        aria-label={`Редактировать преподавателя ${teacher.full_name}`}
                        onClick={() => options.openEdit(teacher)}
                      >
                        <Pencil />
                      </IconButton>
                    </div>
                  </div>
                  {!collapsed() && (
                    <Button
                      type="button"
                      class="add-student"
                      onClick={() => {
                        options.setTeacherId(String(teacher.id));
                        options.setStudentId(
                          (options.allStudents ?? [])[0]?.id ? String((options.allStudents ?? [])[0].id) : "",
                        );
                        options.setModal({
                          mode: "assign",
                        });
                      }}
                    >
                      <Plus />
                      Назначить ученика
                    </Button>
                  )}
                  {!collapsed() && (
                    <div class="student-list">
                      <For each={students()}>
                        {(student) => (
                          <div class="student-card">
                            <StudentPerson student={student} />
                            <EditStudentButton student={student} onEdit={options.openEdit} />
                            <IconButton
                              class="graph-person-action"
                              title="Отвязать от учителя"
                              aria-label={"Отвязать ученика " + student.full_name + " от учителя"}
                              onClick={() => options.unassignStudent(student)}
                            >
                              <Unlink />
                            </IconButton>
                          </div>
                        )}
                      </For>
                      {!students().length && <div class="empty-students">Нет назначенных учеников</div>}
                    </div>
                  )}
                </section>
              );
            }}
          </For>
        </div>
        {!options.loading && !(options.allTeachers ?? []).length && (
          <EmptyState>
            <GraduationCap />
            <b>Пока нет учителей</b>
            <span>Добавьте первого учителя, затем учеников и связи между ними.</span>
          </EmptyState>
        )}
        {!!(options.unassignedStudents ?? []).length && (
          <section class="unassigned">
            <h2 class="unassigned-title">Ученики без учителя</h2>
            <div class="unassigned-grid">
              <For each={options.unassignedStudents ?? []}>
                {(student) => (
                  <div class="student-card unassigned-student-card">
                    <StudentPerson student={student} />
                    <div class="unassigned-student-actions">
                      <EditStudentButton student={student} onEdit={options.openEdit} />
                      <Button
                        type="button"
                        size="small"
                        variant="outline"
                        disabled={!(options.allTeachers ?? []).length}
                        onClick={() => {
                          options.setStudentId(String(student.id));
                          options.setTeacherId(String((options.allTeachers ?? [])[0]?.id || ""));
                          options.setModal({
                            mode: "assign",
                          });
                        }}
                      >
                        Назначить
                      </Button>
                    </div>
                  </div>
                )}
              </For>
            </div>
          </section>
        )}
      </div>
    </>
  );
}
