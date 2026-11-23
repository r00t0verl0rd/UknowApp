import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const dialogs = readFileSync(new URL("../src/features/users/components/UserDialogs.jsx", import.meta.url), "utf8");
const styles = readFileSync(new URL("../src/shared/styles/components/button-sizing.scss", import.meta.url), "utf8");

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

test("participant dialogs remain compact across screen sizes with accessible touch targets", () => {
  assert.match(styles, /dialog\.native-dialog:is\(\.create-participant-modal, \.participant-profile-modal\)\[open\]/);
  assert.match(styles, /width:min\(430px, calc\(100vw - 24px\)\)/);
  assert.match(styles, /min-height:40px;\s*height:40px;[\s\S]*?font-size:16px;/);
  assert.match(styles, /\.modal-actions\.participant-form-actions/);
  assert.match(styles, /--icon-action-size:44px/);
  assert.match(styles, /@media \(max-width: 480px\)/);
});
