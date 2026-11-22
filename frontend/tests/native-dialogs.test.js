import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

const frontend = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const read = p => readFileSync(path.join(frontend, p), "utf8");

test("all application modals use native browser dialog top layer", () => {
  const modal = read("src/shared/components/Modal.jsx");
  assert.match(modal, /<dialog\s+ref=\{dialogRef\}/);
  assert.match(modal, /dialog\.showModal\(\)/);
  assert.match(modal, /onCancel=\{handleCancel\}/);
  assert.match(modal, /onClick=\{handleBackdropClick\}/);
  assert.doesNotMatch(modal, /<div class="overlay"/);
});

test("errors and success notifications use native browser dialogs", () => {
  const toast = read("src/shared/components/AppToast.jsx");
  assert.match(toast, /<dialog/);
  assert.match(toast, /dialog\.showModal\(\)/);
  assert.match(toast, /dialog\.show\(\)/);
  assert.match(toast, /activeModal\(\) \|\| document\.body/);
  assert.match(toast, /role=\{isError\(\) \? "alertdialog" : "dialog"\}/);
});

test("user forms and code dialogs share right aligned equal height actions", () => {
  const users = read("src/features/users/components/UserDialogs.jsx");
  const css = read("src/shared/styles/native-dialogs.scss");
  assert.match(users, /className="password-code-refresh"/);
  assert.match(users, /Выдать новый код\?/);
  assert.match(users, /closeOnBackdrop=\{!options\.savingUser\}/);
  assert.match(users, /<div class="modal-actions">\s*<Button variant="ghost"/);
  assert.match(css, /justify-content:\s*flex-end\s*!important/);
  assert.match(css, /height:\s*44px\s*!important/);
  assert.match(css, /\.panel-access-value \.password-code-refresh/);
  assert.match(css, /\.credential-field-value \.ui-icon-button/);
});

test("popup lists are native select controls", () => {
  const select = read("src/shared/components/ToolbarSelect.jsx");
  const css = read("src/shared/styles/native-dialogs.scss");
  assert.match(select, /<select/);
  assert.match(css, /appearance:\s*auto\s*!important/);
});
