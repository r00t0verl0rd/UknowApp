import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const read = file => readFileSync(path.join(root, file), "utf8");

test("login uses the same full-viewport surface as all workspaces", () => {
  const page = read("src/app/authentication/LoginPage.jsx");
  const css = read("src/shared/styles/login.scss");
  const imports = read("src/shared/styles/index.scss");
  const critical = read("public/critical.css");

  assert.match(page, /<main class="login-screen">/);
  assert.match(page, /class="login-brand"/);
  assert.match(page, /src="\/logo-main\.svg"/);
  assert.match(page, /class="login-submit"/);
  assert.match(imports, /@use "\.\/login";/);
  assert.match(css, /:root\[data-theme\]:has\(\.login-screen\)/);
  assert.match(css, /background:\s*var\(--workspace-background\)\s*!important/);
  assert.match(css, /min-height:\s*100dvh/);
  assert.match(css, /@media \(max-width: 1024px\) and \(display-mode: browser\)/);
  assert.match(css, /min-height:\s*100lvh/);
  assert.match(css, /env\(safe-area-inset-bottom/);
  assert.doesNotMatch(css, /position:\s*fixed/);
  assert.match(critical, /background: #202938/);
  assert.match(critical, /background: #faf8fd/);
});

test("first paint does not wait for remote font requests", () => {
  const html = read("index.html");
  const entry = read("src/main.jsx");

  assert.doesNotMatch(html, /fonts\.googleapis|fonts\.gstatic|id="web-fonts"/);
  assert.doesNotMatch(entry, /web-fonts/);
  assert.match(html, /src="\/src\/main\.jsx"/);
});
