import "../shared/styles/workspace/boards.scss";
import "../shared/styles/teacher.scss";
import { For, Match, Switch, createEffect, createSignal, lazy } from "solid-js";
const ChatsView = lazy(() => import("./ChatsView.jsx"));
import CountBadge from "../shared/components/CountBadge.jsx";
import { IconGraduationCap as GraduationCap, IconSmile as Smile } from "../shared/components/Icons.jsx";

// Граф учеников занимает пространство кабинета и не прокручивается отдельно.
const STUDENT_WIDTH = 170;
const STUDENT_HEIGHT = 76;
const STUDENT_COLUMNS_SPACING = 184;
const STUDENT_ROWS_SPACING = 114;

function buildTeacherOrbit(count, availableWidth = 900) {
  const width = Math.max(320, Math.round(availableWidth));
  const centerX = width / 2;

  if (count < 3) {
    const centerY = 162;
    const studentY = 367;
    const offset = Math.min(165, (width - STUDENT_WIDTH - 30) / 4);
    const xs = count === 1 ? [centerX] : count === 2
      ? [centerX - offset, centerX + offset] : [];
    return {
      width, height:470, centerX, centerY, rings:[],
      links:xs.map(x => ({x1:centerX, y1:centerY, x2:x, y2:studentY})),
      nodes:xs.map((x,index) => ({index,x,y:studentY})),
    };
  }

  if (count <= 10) {
    const radiusX = Math.max(178, Math.min(330, (width - STUDENT_WIDTH) / 2 - 25));
    let radiusY = 240;
    let offsets = [];
    // Высокий овал не даёт группам пересекаться.
    for (let attempt = 0; attempt < 25; attempt++) {
      offsets = Array.from({length:count}, (_,index) => {
        const angle = -Math.PI / 2 + index * 2 * Math.PI / count;
        return {index,x:radiusX*Math.cos(angle),y:radiusY*Math.sin(angle)};
      });
      const overlaps = offsets.some((node,i) => offsets.some((other,j) =>
        i < j && Math.abs(node.x-other.x) < STUDENT_WIDTH+12
          && Math.abs(node.y-other.y) < STUDENT_HEIGHT+13));
      const hitsTeacher = offsets.some(node =>
        Math.abs(node.x) < (214+STUDENT_WIDTH)/2 + 10
          && Math.abs(node.y) < (168+STUDENT_HEIGHT)/2 + 12);
      if (!overlaps && !hitsTeacher) break;
      radiusY += 38;
    }
    const centerY = radiusY + 80;
    return {
      width, height:2*centerY, centerX, centerY,
      rings:[{radiusX,radiusY}],
      links:offsets.map(node => ({
        x1:centerX,y1:centerY,x2:centerX+node.x,y2:centerY+node.y,
      })),
      nodes:offsets.map(node => ({
        index:node.index,x:centerX+node.x,y:centerY+node.y,
      })),
    };
  }

  // При большой группе расширяем схему вокруг преподавателя.
  const columns = Math.max(2, Math.min(4, Math.floor((width-30)/190)));
  const columnOffsets = Array.from({length:columns}, (_,i) =>
    (i-(columns-1)/2)*STUDENT_COLUMNS_SPACING);
  const positions = [];
  for (let row = 0; positions.length < count; row++) {
    const ys = row === 0 ? [0] : [-row*STUDENT_ROWS_SPACING, row*STUDENT_ROWS_SPACING];
    for (const y of ys) {
      // Сохраняем симметрию неполного ряда.
      const sorted = [...columnOffsets].sort((a,b) => Math.abs(b)-Math.abs(a) || a-b);
      for (const x of sorted) {
        if (Math.abs(x) < (214+STUDENT_WIDTH)/2 + 8
            && Math.abs(y) < (168+STUDENT_HEIGHT)/2 + 14) continue;
        positions.push({index:positions.length,x,y});
        if (positions.length === count) break;
      }
      if (positions.length === count) break;
    }
  }

  const maxY = Math.max(...positions.map(node => Math.abs(node.y)), 180);
  const centerY = maxY + 95;
  const radiusX = Math.min((width-STUDENT_WIDTH)/2-19, 345);
  const ringCount = Math.max(1, Math.ceil(maxY/230));
  const rings = Array.from({length:ringCount}, (_,i) => ({
    radiusX:radiusX - i%2*8,
    radiusY:Math.min(maxY+20,(i+1)*230),
  }));
  const links = positions.map(node => {
    const parent = positions
      .filter(candidate => Math.abs(candidate.y)<Math.abs(node.y)-25)
      .sort((a,b) => Math.abs(a.x-node.x)-Math.abs(b.x-node.x))[0];
    const nearCenter = Math.abs(node.y)<=STUDENT_ROWS_SPACING;
    return {
      x1:centerX+(nearCenter?0:parent?.x || 0),
      y1:centerY+(nearCenter?0:parent?.y || 0),
      x2:centerX+node.x,
      y2:centerY+node.y,
    };
  });
  return {
    width, height:2*centerY, centerX, centerY, rings, links,
    nodes:positions.map(node => ({
      index:node.index,x:centerX+node.x,y:centerY+node.y,
    })),
  };
}

function TeacherStructurePage(options) {
  // Показываем только назначения преподавателя.
  const students = () => options.context.chatState.chats.filter(
    (chat) => chat.student && chat.type !== "personal",
  );
  const [availableWidth, setAvailableWidth] = createSignal(900);
  const layout = () => buildTeacherOrbit(students().length, availableWidth());
  const teacherName = () => options.context.profile?.full_name || "Преподаватель";
  let stage;

  // Высоту схемы рассчитываем по ширине колонки и числу учеников.
  createEffect(() => [], () => {
    if (!stage) return;
    const measure = () => setAvailableWidth(Math.max(320, Math.round(stage.clientWidth || 900)));
    measure();
    const observer = typeof ResizeObserver === "function" ? new ResizeObserver(measure) : null;
    if (observer) observer.observe(stage);
    else window.addEventListener("resize", measure);
    return () => {
      observer?.disconnect();
      window.removeEventListener("resize", measure);
    };
  });

  return (
    <section class="teacher-structure teacher-zen" aria-label="Структура преподавателя">
      <header class="teacher-zen-intro">
        <div class="teacher-zen-count">
          <span class="student-dot" aria-hidden="true" />
          <span>Мои ученики</span>
          <CountBadge as="b" value={students().length} label="учеников" />
        </div>
      </header>

      <div class="teacher-zen-stage" ref={stage} role="group" aria-label="Граф учеников преподавателя">
        <div
          class={["teacher-zen-canvas", { "is-small-class": students().length > 0 && students().length <= 2 }]}
          style={{
            "--zen-canvas-height": layout().height + "px",
            "--zen-center-y": layout().centerY + "px",
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

          <div class="teacher-zen-center" tabindex="0" aria-label={"Преподаватель " + teacherName()}>
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
