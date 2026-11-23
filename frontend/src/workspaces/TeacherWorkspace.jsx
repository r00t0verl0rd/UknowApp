import { For, Match, Switch } from "solid-js";
import BoardsPlaceholder from "./BoardsPlaceholder.jsx";
import ChatsView from "./ChatsView.jsx";
import CountBadge from "../shared/components/CountBadge.jsx";
import EmptyState from "../shared/components/EmptyState.jsx";
import { IconGraduationCap as GraduationCap, IconSmile as Smile } from "../shared/components/Icons.jsx";

function TeacherStructurePage(options) {
  // Только собственные активные назначения, уже отфильтрованные сервером
  // /panel/conversations для роли teacher. Административных действий нет.
  const students = () => options.context.chatState.chats.filter((chat) => chat.student && chat.type !== "personal");
  return (
    <section class="teacher-structure" aria-label="Структура преподавателя">
      <div class="graph-legend-row">
        <div class="legend graph-legend">
          <div class="graph-legend-item">
            <span class="student-dot" />
            Мои ученики
            <CountBadge as="b" value={students().length} label="учеников" />
          </div>
        </div>
      </div>
      <div class="teacher-branch">
        <div class="teacher-card">
          <div class="person-main">
            <div class="avatar teacher-avatar"><GraduationCap /></div>
            <div class="person-info">
              <b>{options.context.profile?.full_name || "Преподаватель"}</b>
              <small>Учитель · {students().length} учен.</small>
            </div>
          </div>
        </div>
        <div class="student-list">
          <For each={students()}>
            {(chat) => (
              <div class="student-card">
                <div class="person-main">
                  <div class="avatar student-avatar"><Smile /></div>
                  <div class="person-info"><b>{chat.student.full_name}</b></div>
                </div>
              </div>
            )}
          </For>
          {!options.context.inboxLoading && !students().length && (
            <EmptyState>Пока нет назначенных учеников</EmptyState>
          )}
        </div>
      </div>
    </section>
  );
}

export default function TeacherWorkspace(options) {
  return (
    <Switch>
      <Match when={options.context.page === "boards"}><BoardsPlaceholder /></Match>
      <Match when={options.context.page === "graph"}>
        <TeacherStructurePage context={options.context} />
      </Match>
      <Match when={options.context.page === "chats"}>
        <ChatsView context={options.context} />
      </Match>
    </Switch>
  );
}
