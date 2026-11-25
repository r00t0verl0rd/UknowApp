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

test("production CSS is split by authenticated workspace", () => {
  const manifest = JSON.parse(read("dist/.vite/manifest.json"));
  const initial = Object.keys(manifest).find(key => manifest[key].isEntry && key.endsWith("index.html"));
  assert.ok(initial, "Missing production entry in the Vite manifest");
  function cssClosure(key, seen = new Set()) {
    if (seen.has(key)) return [];
    seen.add(key);
    const chunk = manifest[key];
    assert.ok(chunk, "Missing manifest chunk: " + key);
    return [...(chunk.css ?? []), ...(chunk.imports ?? []).flatMap(dep => cssClosure(dep, seen))];
  }
  const css = keys => [...new Set(keys)].map(file => read("dist/" + file)).join("\n");
  const initialCss = css(cssClosure(initial));
  const roleKeys = Object.fromEntries(["Admin", "Teacher", "Student"].map(role => [
    role, Object.keys(manifest).find(key => key.endsWith("/" + role + "Workspace.jsx")),
  ]));
  for (const role of Object.keys(roleKeys)) assert.ok(roleKeys[role], "Missing workspace manifest entry: " + role);
  const adminFeatures = [/\.data-stat-card\b/, /\.user-info-login\b/, /\.teacher-collapse-btn\b/];
  const teacherFeature = /\.teacher-zen-stage\b/;
  const restoreFeature = /\.restore-flow-progress-bar\b/;
  for (const marker of [...adminFeatures, teacherFeature, restoreFeature]) assert.doesNotMatch(initialCss, marker);
  assert.match(initialCss, /\.restore-login-notice\b/);
  const admin = css(cssClosure(roleKeys.Admin));
  for (const marker of adminFeatures) assert.match(admin, marker);
  assert.doesNotMatch(admin, teacherFeature);
  const teacher = css(cssClosure(roleKeys.Teacher));
  assert.match(teacher, teacherFeature);
  for (const marker of [...adminFeatures, restoreFeature]) assert.doesNotMatch(teacher, marker);
  const student = css(cssClosure(roleKeys.Student));
  for (const marker of [...adminFeatures, teacherFeature, restoreFeature]) assert.doesNotMatch(student, marker);
  for (const role of Object.keys(roleKeys)) {
    assert.match(initialCss + css(cssClosure(roleKeys[role])), /\.boards-placeholder\b/);
  }
  const restore = Object.keys(manifest).find(key => key.endsWith("/RestoreFlowDialog.jsx"));
  assert.ok(restore, "Restore dialog must remain an independent lazy entry");
  assert.match(css(cssClosure(restore)), restoreFeature);
});
