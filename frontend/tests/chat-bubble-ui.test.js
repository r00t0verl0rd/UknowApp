import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

const frontend = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const countBadge = readFileSync(path.join(frontend, "src/shared/components/CountBadge.jsx"), "utf8");

test("conversation count badges expose the full unread count", () => {
  assert.match(countBadge, /\{count\(\)\}/);
  assert.doesNotMatch(countBadge, /99\+/);
  assert.match(countBadge, /\$\{count\(\)\} \$\{props\.label\}/);
});

test("personal chat recipient picker contains only alphabetically sorted names", () => {
  const dialogs = readFileSync(path.join(frontend, "src/features/conversations/components/ChatDialogs.jsx"), "utf8");
  assert.match(dialogs, /\.sort\(\(a, b\) => a\.full_name\.localeCompare\(b\.full_name, "ru"/);
  assert.match(dialogs, /<option value=\{user\.id\}>\{user\.full_name\}<\/option>/);
  assert.doesNotMatch(dialogs, /№\{user\.id\}/);
  assert.doesNotMatch(dialogs, /\{user\.role === "teacher" \? "Учитель" : "Ученик"\}/);
});
