import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const read = file => readFileSync(path.join(root, file), "utf8");

test("first paint does not wait for remote font requests", () => {
  const html = read("index.html");
  const entry = read("src/main.jsx");

  assert.doesNotMatch(html, /fonts\.googleapis|fonts\.gstatic|id="web-fonts"/);
  assert.doesNotMatch(entry, /web-fonts/);
  assert.match(html, /src="\/src\/main\.jsx"/);
});
