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

  assert.match(html, /<link rel="stylesheet" href="\/src\/shared\/styles\/critical\.css"/);
  assert.doesNotMatch(html, /<style(?:\s|>)/i);
  const stylesheet = builtHtml.match(/<link rel="stylesheet"[^>]+href="(\/assets\/[^"]+\.css)"/);
  assert.ok(stylesheet, "First paint uses a fingerprinted external stylesheet");
  const css = readFileSync(path.join(frontend, "dist", stylesheet[1]), "utf8");
  assert.match(css, /#root/);
  assert.match(css, /min-height:100%/);
  assert.doesNotMatch(builtHtml, /<style(?:\s|>)/i);
  assert.match(html, /<script src="\/theme-init\.js"><\/script>/);
  assert.doesNotMatch(html, /<script>([\s\S]*?)<\/script>/);
  assert.ok(existsSync(path.join(frontend, "public", "theme-init.js")));
  assert.ok(existsSync(path.join(frontend, "dist", "theme-init.js")));

  const sitePolicy = caddy.split("\n").find(line => line.trimStart().startsWith("Content-Security-Policy "));
  assert.ok(sitePolicy, "Site CSP must be present");
  assert.match(sitePolicy, /style-src 'self' https:\/\/fonts\.googleapis\.com/);
  assert.doesNotMatch(sitePolicy, /(?:^|;\s*)style-src\s+[^;]*'unsafe-inline'/);
  assert.match(sitePolicy, /style-src-elem 'self' https:\/\/fonts\.googleapis\.com/);
  assert.match(sitePolicy, /script-src 'self'/);
  assert.doesNotMatch(sitePolicy, /sha256-/);
  assert.match(sitePolicy, /style-src-attr 'unsafe-inline'/);
  assert.doesNotMatch(sitePolicy, /style-src-elem[^;]*'unsafe-inline'/);
});
