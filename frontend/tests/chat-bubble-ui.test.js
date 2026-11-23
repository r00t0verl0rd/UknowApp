import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

const frontend = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const bubble = readFileSync(path.join(frontend, "src/features/conversations/components/MessageBubble.jsx"), "utf8");
const styles = readFileSync(path.join(frontend, "src/shared/styles/features/conversations.scss"), "utf8");

test("delivery details use a native popover, not an error modal", () => {
  assert.match(bubble, /popover="auto"/);
  assert.match(bubble, /popovertarget=\{deliveryPopoverId\}/);
  assert.match(bubble, /aria-label="Подробности внешней доставки"/);
  assert.match(bubble, /message-detail-btn/);
  assert.doesNotMatch(bubble, /options\.onError\(/);
  assert.doesNotMatch(bubble, /class="btn small"/);
});

test("sender name is always visible for all conversation participants", () => {
  assert.match(bubble, /<div class="message-topline">\s*<b>\{options\.message\.sender\}<\/b>/);
  assert.doesNotMatch(bubble, /options\.viewerRole === "teacher" && options\.message\.sender_role/);
  assert.doesNotMatch(bubble, /\{[^}]*options\.message\.sender_role[^}]*&&\s*\(\s*<b>/);
});

test("message text and unobtrusive icon actions share desktop and mobile styles", () => {
  assert.match(styles, /\.message > p \{[^}]*font-size:15px;[^}]*font-weight:400;[^}]*line-height:1\.58;/s);
  assert.match(styles, /\.message-topline > b \{[^}]*font-size:11px;/s);
  assert.match(styles, /\.message \{[^}]*padding:11px 14px 12px;/s);
  assert.match(styles, /:root\[data-theme="dark-soft"\] \.message \.ui-icon-button:is\(\.message-delete-btn, \.message-detail-btn\)/);
  assert.match(styles, /\.message-delivery-popover:popover-open/);
  assert.doesNotMatch(bubble, /tone="danger"/);
});
