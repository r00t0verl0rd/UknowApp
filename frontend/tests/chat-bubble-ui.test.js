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
  assert.match(bubble, /getDeliveryDetails\(options\.message\.metadata\)/);
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
  assert.match(bubble, /<div class="message-topline">\s*<b>\{options\.message\.sender\}<\/b>/);
  assert.doesNotMatch(bubble, /options\.viewerRole === "teacher" && options\.message\.sender_role/);
  assert.doesNotMatch(bubble, /\{[^}]*options\.message\.sender_role[^}]*&&\s*\(\s*<b>/);
});

test("chat header actions align and remain clickable on touch and desktop", () => {
  assert.match(styles, /\.message-topline \{[^}]*display:grid;[^}]*grid-template-columns:minmax\(0, 1fr\) auto;/s);
  assert.match(styles, /\.message-tools \{[^}]*align-items:center;[^}]*height:36px;/s);
  assert.match(styles, /--icon-action-size:36px/);
  assert.match(styles, /touch-action:manipulation/);
  assert.match(bubble, /class="message-detail-btn"[\s\S]*?popovertarget=\{deliveryPopoverId\}/);
  assert.match(bubble, /class="message-delete-btn"[\s\S]*?onClick=\{\(\) => options\.onDelete\?\.\(options\.message\)\}/);
});

test("message text and unobtrusive icon actions share desktop and mobile styles", () => {
  assert.match(styles, /\.message > p \{[^}]*font-size:15px;[^}]*font-weight:400;[^}]*line-height:1\.58;/s);
  assert.match(styles, /\.message-topline > b \{[^}]*font-size:11px;/s);
  assert.match(styles, /\.message \{[^}]*padding:11px 14px 12px;/s);
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
