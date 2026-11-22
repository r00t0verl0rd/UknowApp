import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

const frontend = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

test("critical CSS stays external and compatible with production CSP", () => {
  const html = readFileSync(path.join(frontend, "index.html"), "utf8");
  const builtHtml = readFileSync(path.join(frontend, "dist", "index.html"), "utf8");
  const caddy = readFileSync(path.join(frontend, "Caddyfile"), "utf8");

  assert.match(html, /<link rel="stylesheet" href="\/critical\.css"/);
  assert.doesNotMatch(html, /<style(?:\s|>)/i);
  assert.match(builtHtml, /critical\.css/);
  assert.doesNotMatch(builtHtml, /<style(?:\s|>)/i);
  assert.ok(existsSync(path.join(frontend, "dist", "critical.css")));

  const sitePolicy = caddy.split("\n").find(line => line.trimStart().startsWith("Content-Security-Policy "));
  assert.ok(sitePolicy, "Site CSP must be present");
  assert.match(sitePolicy, /style-src 'self' https:\/\/fonts\.googleapis\.com/);
  assert.doesNotMatch(sitePolicy, /style-src[^;]*'unsafe-inline'/);
});
