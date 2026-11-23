import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

const frontend = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const bubble = readFileSync(path.join(frontend, "src/features/conversations/components/MessageBubble.jsx"), "utf8");
const styles = readFileSync(path.join(frontend, "src/shared/styles/features/conversations.scss"), "utf8");
const countBadge = readFileSync(path.join(frontend, "src/shared/components/CountBadge.jsx"), "utf8");

test("delivery details use a native popover, not an error modal", () => {
  assert.match(bubble, /popover="auto"/);
  assert.match(bubble, /popovertarget=\{deliveryPopoverId\}/);
  assert.match(bubble, /aria-label="Подробности внешней доставки"/);
  assert.match(bubble, /message-detail-btn/);
  assert.match(bubble, /Сообщение доставлено в UknowApp/);
  assert.match(bubble, /getDeliveryDetails\(options\.message\.metadata,\s*true\)/);
  assert.match(styles, /\.message-delivery-popover h3 \{[^}]*color:var\(--success\)/s);
  assert.doesNotMatch(bubble, /options\.onError\(/);
  assert.doesNotMatch(bubble, /class="btn small"/);
});

test("related popups communicate outcomes before caveats", () => {
  const chats = readFileSync(path.join(frontend, "src/features/conversations/state/createChatsController.js"), "utf8");
  const feedback = readFileSync(path.join(frontend, "src/shared/components/AppToast.jsx"), "utf8");
  const backup = readFileSync(path.join(frontend, "src/features/administration/RestoreFlowDialog.jsx"), "utf8");
  assert.match(chats, /options\.notify\(\s*"Сообщение удалено из UknowApp/);
  assert.doesNotMatch(chats, /Не удалось удалить копии во внешних мессенджерах/);
  assert.match(feedback, /"Не получилось"/);
  assert.match(backup, /Данные из резервной копии восстановлены/);
});

test("sender name is always visible for all conversation participants", () => {
  assert.match(bubble, /<div class="message-topline">\s*<b data-chat-name-role=\{options\.message\.sender_role\}>\{options\.message\.sender\}<\/b>/);
  assert.doesNotMatch(bubble, /options\.viewerRole === "teacher" && options\.message\.sender_role/);
  assert.doesNotMatch(bubble, /\{[^}]*options\.message\.sender_role[^}]*&&\s*\(\s*<b>/);
});

test("chat header actions align and remain clickable on touch and desktop", () => {
  assert.match(styles, /\.message-topline \{[^}]*display:grid;[^}]*grid-template-columns:minmax\(0, 1fr\) auto;/s);
  assert.match(styles, /\.message-tools \{[^}]*align-items:center;/s);
  assert.match(styles, /--icon-action-size:var\(--message-action-height, 28px\)/);
  assert.match(styles, /height:var\(--icon-action-size\);\s*min-height:var\(--icon-action-size\);\s*aspect-ratio:1;/);
  assert.match(styles, /touch-action:manipulation/);
  assert.match(bubble, /class="message-detail-btn"[\s\S]*?popovertarget=\{deliveryPopoverId\}/);
  assert.match(bubble, /class="message-delete-btn"[\s\S]*?onClick=\{\(\) => options\.onDelete\?\.\(options\.message\)\}/);
});

test("message text and unobtrusive icon actions share desktop and mobile styles", () => {
  assert.match(styles, /\.message-content > p \{[^}]*font-size:15px;[^}]*font-weight:400;[^}]*line-height:1\.58;/s);
  assert.match(styles, /\.message-topline > b \{[^}]*font-size:11px;/s);
  assert.match(styles, /\.message \{[^}]*padding:5px 10px 8px;/s);
  assert.match(styles, /:root\[data-theme="dark-soft"\] \.message \.ui-icon-button:is\(\.message-delete-btn, \.message-detail-btn\)/);
  assert.match(styles, /\.message-delivery-popover:popover-open/);
  assert.doesNotMatch(bubble, /tone="danger"/);
});

test("conversation count badges show the full number and grow into a pill", () => {
  assert.match(countBadge, /const formatted = \(\) => count\(\);/);
  assert.doesNotMatch(countBadge, /99\+/);
  assert.match(countBadge, /\$\{formatted\(\)\} \$\{props\.label\}/);
  assert.match(styles, /\.chat-tab-count \{[^}]*min-width:22px;[^}]*width:max-content;[^}]*max-width:none;[^}]*padding:0 6px;[^}]*border-radius:999px;[^}]*white-space:nowrap;/s);
});

test("toast duration and viewport motion keep feedback readable and Safari scrolling steady", () => {
  const app = readFileSync(path.join(frontend, "src/app/App.jsx"), "utf8");
  const viewport = readFileSync(path.join(frontend, "src/shared/services/viewportEnvironment.js"), "utf8");
  const tabs = readFileSync(path.join(frontend, "src/shared/styles/components/chat-controls.scss"), "utf8");
  assert.match(app, /setTimeout\(\(\) => setNotice\(null\), 6000\)/);
  assert.match(viewport, /const workspaceOpen = open \|\| prepareChat;/);
  assert.match(viewport, /const onViewportScroll = \(\) => \{/);
  assert.match(styles, /\.chat-composer textarea \{[^}]*height:84px;[^}]*min-height:84px;[^}]*max-height:84px;/s);
  assert.match(styles, /background-color var\(--ui-transition-fast\)/);
  assert.match(tabs, /font-weight:700;/);
});


test("admin participant conversations use one-line linked names and shared message filter", () => {
  const chats = readFileSync(path.join(frontend, "src/features/conversations/ChatsPage.jsx"), "utf8");
  assert.match(chats, /class="participant-pair"/);
  assert.match(chats, /class="participant-pair-arrow" aria-hidden="true">↔<\/span>/);
  assert.match(chats, /<ToolbarSelect\s+class="chat-message-filter"/);
  assert.doesNotMatch(chats, /Сообщение будет отправлено обоим участникам/);
  assert.match(chats, /Напишите сообщение — его увидят ученик и учитель/);
  assert.match(styles, /\.participant-pair \{[^}]*white-space:nowrap;/s);
  assert.match(styles, /\.participant-pair > \[data-chat-name-role\] \{[^}]*text-overflow:ellipsis;/s);
  assert.match(styles, /\.mobile-chat-back \{[^}]*width:48px;[^}]*height:48px;/s);
});
