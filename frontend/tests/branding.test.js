import assert from "node:assert/strict";
import { existsSync, readFileSync, readdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

const frontend = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const read = file => readFileSync(path.join(frontend, file), "utf8");

test("vector UI logo and PNG compatibility icons use the supplied assets", () => {
  const assets = readdirSync(path.join(frontend, "public"))
    .filter(name => /\.(?:svg|png|jpe?g|webp|gif|ico|avif)$/i.test(name)).sort();
  assert.deepEqual(assets, ["logo-192.png", "logo-big.png", "logo-main.svg", "logo-touch.png"]);

  const svg = read("public/logo-main.svg");
  assert.match(svg, /^<svg\b/);
  assert.match(svg, /viewBox=/);
  assert.doesNotMatch(svg, /<image\b|data:image\//i);

  for (const [name, size] of [["logo-touch.png", 180], ["logo-192.png", 192], ["logo-big.png", 512]]) {
    const png = readFileSync(path.join(frontend, "public", name));
    assert.deepEqual([...png.subarray(0, 8)], [137, 80, 78, 71, 13, 10, 26, 10], name);
    assert.equal(png.readUInt32BE(16), size, name);
    assert.equal(png.readUInt32BE(20), size, name);
  }

  const html = read("index.html");
  assert.match(html, /rel="icon" href="\/logo-touch\.png\?v=4" type="image\/png" sizes="180x180"/);
  assert.match(html, /rel="icon" href="\/logo-main\.svg" type="image\/svg\+xml" sizes="any"/);
  assert.match(html, /rel="apple-touch-icon" href="\/logo-touch\.png\?v=4" sizes="180x180"/);
  assert.match(html, /rel="manifest" href="\/manifest\.webmanifest\?v=4"/);
  assert.doesNotMatch(html, /safari-pinned-tab|msapplication-TileImage/i);

  const manifest = JSON.parse(read("public/manifest.webmanifest"));
  assert.deepEqual(manifest.icons, [
    { src: "/logo-192.png", sizes: "192x192", type: "image/png", purpose: "any" },
    { src: "/logo-big.png", sizes: "512x512", type: "image/png", purpose: "any" },
  ]);
  for (const icon of manifest.icons) {
    assert.ok(existsSync(path.join(frontend, "public", icon.src.slice(1))));
  }

  const worker = read("public/sw.js");
  assert.match(worker, /addEventListener\("push"/);
  assert.match(worker, /icon: "\/logo-big\.png"/);
  assert.match(worker, /badge: "\/logo-192\.png"/);

  for (const file of [
    "src/app/authentication/LoginPage.jsx",
    "src/workspaces/WorkspaceLayout.jsx",
    "src/features/graph/StructurePage.jsx",
  ]) {
    const source = read(file);
    assert.match(source, /src="\/logo-main\.svg"/, file);
    assert.doesNotMatch(source, /src="\/logo\.png"/, file);
  }

  assert.match(read("Caddyfile"), /@appIcons path \/logo-main\.svg \/logo-touch\.png \/logo-192\.png \/logo-big\.png \/manifest\.webmanifest/);
  assert.doesNotMatch(read("Dockerfile"), /generate_icons|py3-pillow/);
});

test("boards notice uses the same logo and exact message for every role", () => {
  for (const role of ["Admin", "Teacher", "Student"]) {
    const source = read("src/workspaces/" + role + "Workspace.jsx");
    assert.ok(source.includes('<section class="boards-placeholder" aria-label="Доски">'), role);
    assert.ok(source.includes('<img src="/logo-main.svg" alt="" />'), role);
    assert.ok(source.includes("<h1>Раздел в разработке.</h1>"), role);
    assert.ok(source.includes("Здесь появится удобное пространство для совместной работы, материалов и визуальных задач."), role);
  }
});
