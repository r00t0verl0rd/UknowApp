import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const dialogs = readFileSync(new URL("../src/features/users/components/UserDialogs.jsx", import.meta.url), "utf8");

test("the participant access code is masked by default", () => {
  assert.match(dialogs, /<b>XXX-XXX<\/b>/);
  assert.doesNotMatch(dialogs, /<b>Скрыт<\/b>/);
});
