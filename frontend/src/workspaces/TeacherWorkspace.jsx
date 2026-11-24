import { For, Match, Show, Switch, lazy } from "solid-js";
const ChatsView = lazy(() => import("./ChatsView.jsx"));
import CountBadge from "../shared/components/CountBadge.jsx";
import { IconGraduationCap as GraduationCap, IconSmile as Smile } from "../shared/components/Icons.jsx";

const ORBIT_CAPACITY = 8;

// Keep the constellation readable: the first eight students orbit the
// teacher and additional students remain visible in a separate group.
function orbitPosition(index, count) {
  if (count === 1) return { x: 50, y: 85 };
  const angle = count === 2
    ? Math.PI - index * Math.PI
    : -Math.PI / 2 + index * (Math.PI * 2) / count;
  return {
    x: Math.round((50 + 33 * Math.cos(angle)) * 10) / 10,
    y: Math.round((50 + 35 * Math.sin(angle)) * 10) / 10,
  };
}

function TeacherStructurePage(options) {
  // The teacher only sees their own active assignments from panel/conversations.
  // This view is intentionally read-only, unlike the administrator's graph.
  const students = () => options.context.chatState.chats.filter(
    (chat) => chat.student && chat.type !== "personal",
  );
  const orbitStudents = () => students().slice(0, ORBIT_CAPACITY);
  const moreStudents = () => students().slice(ORBIT_CAPACITY);
  const teacherName = () => options.context.profile?.full_name || "Преподаватель";

  return (
    <section class="teacher-structure teacher-zen" aria-label="Структура преподавателя">
      <header class="teacher-zen-intro">
        <div>
          <span class="teacher-zen-eyebrow">МОЙ УЧЕБНЫЙ КРУГ</span>
          <h1>Вместе к новым знаниям</h1>
          <p>Вы в центре, а ваши ученики — рядом.</p>
        </div>
        <div class="teacher-zen-count">
          <span class="student-dot" aria-hidden="true" />
          <span>Мои ученики</span>
          <CountBadge as="b" value={students().length} label="учеников" />
        </div>
      </header>

      <div class="teacher-zen-stage" classList={{ "is-empty": !students().length }}>
        <span class="teacher-zen-ring teacher-zen-ring-outer" aria-hidden="true" />
        <span class="teacher-zen-ring teacher-zen-ring-inner" aria-hidden="true" />
        <svg class="teacher-zen-links" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
          <For each={orbitStudents()}>
            {(_chat, index) => (
              <line
                x1="50"
                y1="50"
                x2={orbitPosition(index(), orbitStudents().length).x}
                y2={orbitPosition(index(), orbitStudents().length).y}
              />
            )}
          </For>
        </svg>

        <div class="teacher-zen-center">
          <div class="teacher-zen-center-avatar"><GraduationCap size={30} aria-hidden="true" /></div>
          <span class="teacher-zen-center-label">ВАШ ЦЕНТР</span>
          <strong title={teacherName()}>{teacherName()}</strong>
          <small>Преподаватель · {students().length} учен.</small>
        </div>

        <ul class="teacher-zen-satellites" aria-label="Ученики преподавателя">
          <For each={orbitStudents()}>
            {(chat, index) => (
              <li
                class="teacher-zen-student"
                style={{
                  "--orbit-x": orbitPosition(index(), orbitStudents().length).x + "%",
                  "--orbit-y": orbitPosition(index(), orbitStudents().length).y + "%",
                }}
              >
                <span class="teacher-zen-student-avatar"><Smile size={20} aria-hidden="true" /></span>
                <span class="teacher-zen-student-name" title={chat.student.full_name}>
                  {chat.student.full_name}
                </span>
              </li>
            )}
          </For>
        </ul>

        {!options.context.inboxLoading && !students().length && (
          <p class="teacher-zen-empty">Когда появятся ученики, здесь расцветёт ваш учебный круг.</p>
        )}
      </div>

      <Show when={moreStudents().length}>
        <div class="teacher-zen-more">
          <h2>Ещё ученики</h2>
          <ul class="teacher-zen-more-grid">
            <For each={moreStudents()}>
              {(chat) => (
                <li class="teacher-zen-extra-student">
                  <span class="teacher-zen-student-avatar"><Smile size={18} aria-hidden="true" /></span>
                  <span title={chat.student.full_name}>{chat.student.full_name}</span>
                </li>
              )}
            </For>
          </ul>
        </div>
      </Show>
    </section>
  );
}

export default function TeacherWorkspace(options) {
  return (
    <Switch>
      <Match when={options.context.page === "boards"}>
        <section class="boards-placeholder" aria-label="Доски">
          <img src="/logo-main.svg" alt="" />
          <h1>Раздел в разработке.</h1>
          <p>Здесь появится удобное пространство для совместной работы, материалов и визуальных задач.</p>
        </section>
      </Match>
      <Match when={options.context.page === "graph"}>
        <TeacherStructurePage context={options.context} />
      </Match>
      <Match when={options.context.page === "chats"}>
        <ChatsView context={options.context} />
      </Match>
    </Switch>
  );
}
