import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

const frontend = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const bubble = readFileSync(path.join(frontend, "src/features/conversations/components/MessageBubble.jsx"), "utf8");
const countBadge = readFileSync(path.join(frontend, "src/shared/components/CountBadge.jsx"), "utf8");

test("delivery details use a native popover, not an error modal", () => {
  assert.match(bubble, /popover="auto"/);
  assert.match(bubble, /popovertarget=\{deliveryPopoverId\}/);
  assert.match(bubble, /aria-label="Подробности внешней доставки"/);
  assert.match(bubble, /message-detail-btn/);
  assert.match(bubble, /Сообщение доставлено в UknowApp/);
  assert.match(bubble, /getDeliveryDetails\(options\.message\.metadata,\s*true,\s*options\.deliveryRecipients \|\| \[\]\)/);
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
  assert.match(bubble, /<div class="message-topline">\s*<b data-chat-name-role=\{options\.message\.sender_role\}>\s*<AutoFitText text=\{options\.message\.sender\}/);
  assert.doesNotMatch(bubble, /options\.viewerRole === "teacher" && options\.message\.sender_role/);
  assert.doesNotMatch(bubble, /\{[^}]*options\.message\.sender_role[^}]*&&\s*\(\s*<b>/);
});

test("conversation count badges expose the full unread count", () => {
  assert.match(countBadge, /\{count\(\)\}/);
  assert.doesNotMatch(countBadge, /99\+/);
  assert.match(countBadge, /\$\{count\(\)\} \$\{props\.label\}/);
});

test("unread personal tab uses the standard highlighted unread badge", () => {
  const chats = readFileSync(path.join(frontend, "src/features/conversations/ChatsPage.jsx"), "utf8");
  const personalTab = chats.slice(chats.indexOf('title="Личные диалоги"'), chats.indexOf('title="Личные диалоги"') + 900);
  assert.match(personalTab, /value=\{unreadPersonalCount\(\)\}/);
  assert.match(personalTab, /unread=\{unreadPersonalCount\(\) > 0\}/);
  assert.match(personalTab, /hideWhenZero/);
  const badges = readFileSync(path.join(frontend, "src/shared/components/CountBadge.jsx"), "utf8");
  assert.match(badges, /chat-tab-count--unread/);
});

test("participant names and dialog filters are exposed in chat markup", () => {
  const chats = readFileSync(path.join(frontend, "src/features/conversations/ChatsPage.jsx"), "utf8");
  assert.match(chats, /function ParticipantHeading\(props\)/);
  assert.match(chats, /class="participant-dialog-title"/);
  assert.match(chats, /class="participant-dialog-arrow" aria-hidden="true">↔<\/span>/);
  assert.match(chats, /text=\{title\(\)\}/);
  assert.match(chats, /<AutoFitText text=\{row\(\)\.teacher\.full_name\}/);
  assert.match(chats, /<AutoFitText text=\{row\(\)\.student\.full_name\}/);
  assert.match(chats, /<ToolbarSelect\s+class="chat-message-filter"/);
  assert.match(chats, /Сообщение ученику и учителю…/);
});

test("personal chat recipient picker contains only alphabetically sorted names", () => {
  const dialogs = readFileSync(path.join(frontend, "src/features/conversations/components/ChatDialogs.jsx"), "utf8");
  assert.match(dialogs, /\.sort\(\(a, b\) => a\.full_name\.localeCompare\(b\.full_name, "ru"/);
  assert.match(dialogs, /<option value=\{user\.id\}>\{user\.full_name\}<\/option>/);
  assert.doesNotMatch(dialogs, /№\{user\.id\}/);
  assert.doesNotMatch(dialogs, /\{user\.role === "teacher" \? "Учитель" : "Ученик"\}/);
});

test("observation eye appears only for admin participant conversations", () => {
  const chats = readFileSync(path.join(frontend, "src/features/conversations/ChatsPage.jsx"), "utf8");
  const icons = readFileSync(path.join(frontend, "src/shared/components/Icons.jsx"), "utf8");
  assert.match(icons, /export const IconEye = icon\("eye"/);
  assert.match(chats, /const showMessageCount = \(\) =>\s*options\.profile\?\.role === "admin" && options\.chatSection === "participants" && !personal\(\)/);
});
