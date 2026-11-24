import { For, Match, Switch, createEffect, lazy } from "solid-js";
const ChatsView = lazy(() => import("./ChatsView.jsx"));
import CountBadge from "../shared/components/CountBadge.jsx";
import { IconGraduationCap as GraduationCap, IconSmile as Smile } from "../shared/components/Icons.jsx";

// Orbit capacity and radii grow together: each circle has room for its cards.
// All students belong to this graph; there is no separate overflow list.
const FIRST_RING_CAPACITY = 10;
const RING_CAPACITY_STEP = 6;
const BASE_RADIUS_X = 330;
const BASE_RADIUS_Y = 240;
const RING_RADIUS_STEP_X = 215;
const RING_RADIUS_STEP_Y = 172;

function buildTeacherOrbit(count) {
  // A small class reads as a hierarchy: teacher above, one student centered
  // below or two students balanced below on the left and right.
  // With 3+ students we switch to concentric circles automatically.
  if (count === 1 || count === 2) {
    const width = 720;
    const height = 560;
    const centerX = width / 2;
    const centerY = height / 2;
    const studentY = centerY + 195;
    const xs = count === 1 ? [centerX] : [centerX - 165, centerX + 165];
    return {
      width,
      height,
      centerX,
      centerY,
      rings: [],
      links: xs.map(x => ({ x1:centerX, y1:centerY, x2:x, y2:studentY })),
      nodes: xs.map((x, index) => ({ index, x, y:studentY })),
    };
  }
  const rings = [];
  const nodes = [];
  let remaining = count;
  let index = 0;
  while (remaining > 0) {
    const ringIndex = rings.length;
    const capacity = FIRST_RING_CAPACITY + RING_CAPACITY_STEP * ringIndex;
    const size = Math.min(remaining, capacity);
    const radiusX = BASE_RADIUS_X + ringIndex * RING_RADIUS_STEP_X;
    const radiusY = BASE_RADIUS_Y + ringIndex * RING_RADIUS_STEP_Y;
    const members = [];

    for (let slot = 0; slot < size; slot++) {
      const angle = size === 1
        ? -Math.PI / 2
        : size === 2
          ? slot * Math.PI
          : -Math.PI / 2 + ((slot + (ringIndex % 2) * 0.5) * 2 * Math.PI) / size;
      const node = {
        index,
        ringIndex,
        x: radiusX * Math.cos(angle),
        y: radiusY * Math.sin(angle),
        angle,
      };
      nodes.push(node);
      members.push(node);
      index++;
    }
    rings.push({ radiusX, radiusY, members });
    remaining -= size;
  }

  const last = rings[rings.length - 1];
  const width = last ? Math.ceil(2 * (last.radiusX + 85 + 44)) : 760;
  const height = last ? Math.ceil(2 * (last.radiusY + 41 + 42)) : 560;
  const centerX = width / 2;
  const centerY = height / 2;

  const links = nodes.map(node => {
    const previous = rings[node.ringIndex - 1]?.members;
    const parent = previous?.length
      ? previous.reduce((nearest, candidate) => {
        const nearestDistance = (nearest.x - node.x) ** 2 + (nearest.y - node.y) ** 2;
        const candidateDistance = (candidate.x - node.x) ** 2 + (candidate.y - node.y) ** 2;
        return candidateDistance < nearestDistance ? candidate : nearest;
      })
      : null;
    return {
      x1: centerX + (parent?.x || 0),
      y1: centerY + (parent?.y || 0),
      x2: centerX + node.x,
      y2: centerY + node.y,
    };
  });

  return {
    width,
    height,
    centerX,
    centerY,
    rings,
    links,
    nodes: nodes.map(node => ({
      index:node.index,
      x:centerX + node.x,
      y:centerY + node.y,
    })),
  };
}

function TeacherStructurePage(options) {
  // Teacher-only active assignments, never the administrator's editable graph.
  const students = () => options.context.chatState.chats.filter(
    (chat) => chat.student && chat.type !== "personal",
  );
  const layout = () => buildTeacherOrbit(students().length);
  const teacherName = () => options.context.profile?.full_name || "Преподаватель";
  let stage;

  // Center the teacher in the visible viewport when the constellation grows
  // beyond the container. Users can still pan to every other circle.
  createEffect(
    () => [layout().width, layout().height],
    () => {
      const frame = requestAnimationFrame(() => {
        if (!stage || window.matchMedia("(max-width: 640px)").matches) return;
        stage.scrollLeft = Math.max(0, (stage.scrollWidth - stage.clientWidth) / 2);
        stage.scrollTop = Math.max(0, (stage.scrollHeight - stage.clientHeight) / 2);
      });
      return () => cancelAnimationFrame(frame);
    },
  );

  return (
    <section class="teacher-structure teacher-zen" aria-label="Структура преподавателя">
      <header class="teacher-zen-intro">
        <div class="teacher-zen-count">
          <span class="student-dot" aria-hidden="true" />
          <span>Мои ученики</span>
          <CountBadge as="b" value={students().length} label="учеников" />
        </div>
      </header>

      <div class="teacher-zen-stage" ref={stage} role="region" aria-label="Граф учеников преподавателя" tabindex="0">
        <div
          class="teacher-zen-canvas"
          classList={{ "is-small-class": students().length > 0 && students().length <= 2 }}
          style={{
            "--zen-canvas-width": layout().width + "px",
            "--zen-canvas-height": layout().height + "px",
          }}
        >
          <svg class="teacher-zen-network" viewBox={`0 0 ${layout().width} ${layout().height}`} aria-hidden="true">
            <For each={layout().rings}>
              {(ring) => (
                <ellipse
                  class="teacher-zen-orbit-ring"
                  cx={layout().centerX}
                  cy={layout().centerY}
                  rx={ring.radiusX}
                  ry={ring.radiusY}
                />
              )}
            </For>
            <For each={layout().links}>
              {(link) => (
                <line class="teacher-zen-link" x1={link.x1} y1={link.y1} x2={link.x2} y2={link.y2} />
              )}
            </For>
          </svg>

          <div class="teacher-zen-center">
            <span class="teacher-zen-center-avatar"><GraduationCap size={30} aria-hidden="true" /></span>
            <strong title={teacherName()}>{teacherName()}</strong>
          </div>

          <ul class="teacher-zen-satellites" aria-label="Ученики преподавателя">
            <For each={layout().nodes}>
              {(node) => (
                <li
                  class="teacher-zen-student"
                  tabindex="0"
                  style={{ "--orbit-x": node.x + "px", "--orbit-y": node.y + "px" }}
                  title={students()[node.index]?.student?.full_name}
                >
                  <span class="teacher-zen-student-avatar"><Smile size={20} aria-hidden="true" /></span>
                  <span class="teacher-zen-student-name">
                    {students()[node.index]?.student?.full_name}
                  </span>
                </li>
              )}
            </For>
          </ul>

          {!options.context.inboxLoading && !students().length && (
            <p class="teacher-zen-empty">Ученики появятся здесь после назначения.</p>
          )}
        </div>
      </div>
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
