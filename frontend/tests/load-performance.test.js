import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const read = file => readFileSync(path.join(root, file), "utf8");

test("the production bundle lazy-loads each role", () => {
  const files = readdirSync(path.join(root, "dist/assets"));
  for (const role of ["AdminWorkspace", "TeacherWorkspace", "StudentWorkspace"]) {
    assert.ok(files.some(file => file.startsWith(role + "-") && file.endsWith(".js")),
      "Missing on-demand chunk: " + role);
  }
  const entry = files.find(file => /^index-[A-Za-z0-9_-]+\.js$/.test(file));
  assert.ok(entry, "Missing JS entry bundle");
  assert.ok(readFileSync(path.join(root, "dist/assets", entry)).byteLength < 115_000,
    "Initial entry must be smaller than the previous 144 kB JavaScript bundle");
});

test("immutable hashed assets cannot fall back to cached SPA HTML", () => {
  const caddy = read("Caddyfile");
  assert.match(caddy, /@hashedAssets path \/assets\/\*/);
  assert.match(caddy, /header @hashedAssets Cache-Control "public, max-age=31536000, immutable"/);
  assert.match(caddy, /handle @hashedAssets \{\s*root \* \/srv\s*file_server\s*\}/);
  assert.match(caddy, /header @html Cache-Control "no-cache, must-revalidate"/);
});
