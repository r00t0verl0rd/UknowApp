import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const dialogs = readFileSync(new URL("../src/features/users/components/UserDialogs.jsx", import.meta.url), "utf8");

test("participant create/edit forms use a single primary action and close icon", () => {
  const form = dialogs.slice(dialogs.indexOf('<form class="stack" onSubmit={options.saveUser}>'));
  const formEnd = form.indexOf('</form>');
  const markup = form.slice(0, formEnd);
  assert.match(markup, /aria-label="Закрыть окно"|class="modal-actions participant-form-actions"/);
  assert.match(markup, /class="modal-actions participant-form-actions"/);
  assert.doesNotMatch(markup, />\s*Отмена\s*</);
  const savePos = markup.indexOf('<Button type="submit" variant="primary"');
  const deletePos = markup.indexOf('class="user-action-btn danger-icon user-delete"');
  assert.ok(savePos !== -1 && deletePos > savePos, "delete icon follows Save");
  assert.match(markup, /aria-label="Удалить участника"/);
  assert.match(dialogs, /title="Удалить участника\?"/);
});

test("the participant access code is masked by default", () => {
  assert.match(dialogs, /<b>XXX-XXX<\/b>/);
  assert.doesNotMatch(dialogs, /<b>Скрыт<\/b>/);
});


test("connection status and feedback use shared theme colors and semantic icons", () => {
  const page = readFileSync(new URL("../src/features/users/UsersPage.jsx", import.meta.url), "utf8");
  const styles = readFileSync(new URL("../src/shared/styles/features/users.scss", import.meta.url), "utf8");
  const toast = readFileSync(new URL("../src/shared/components/AppToast.jsx", import.meta.url), "utf8");
  const feedback = readFileSync(new URL("../src/shared/styles/components/native-dialogs.scss", import.meta.url), "utf8");
  assert.match(page, /telegramId\(user\) \? " is-connected" : ""/);
  assert.match(page, /telegramId\(user\) \? <Check aria-hidden="true" \/> : <Link2/);
  assert.match(page, /"Telegram подключён" : "Telegram не подключён"/);
  assert.match(styles, /\.user-info-line\.is-connected\s*\{\s*color:var\(--success\)/);
  assert.match(styles, /\.user-info-line\s*\{[^}]*color:var\(--muted\)/);
  assert.match(styles, /\.user-info-line > svg\s*\{[^}]*color:inherit/);
  assert.match(styles, /b\.is-unconnected\s*\{\s*color:var\(--muted\)/);
  assert.match(toast, /<Check size=\{20\}/);
  assert.match(feedback, /native-feedback-info \.native-feedback-copy h2\s*\{\s*color:var\(--muted\)/);
  assert.match(feedback, /native-feedback-success \.native-feedback-copy h2\s*\{\s*color:var\(--success\)/);
});
