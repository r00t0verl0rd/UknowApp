import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

const frontend = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const read = relative => readFileSync(path.join(frontend, relative), "utf8");

test("one vector logo is shared by all built-in app branding", () => {
  const brandingFiles = readdirSync(path.join(frontend, "public"))
    .filter(name => /\.(?:svg|png|jpe?g|webp|gif|ico|avif)$/i.test(name));
  assert.ok(brandingFiles.includes("logo-main.svg"));
  assert.ok(brandingFiles.includes("logo-touch.png"));
  assert.ok(brandingFiles.includes("logo-big.png"));
  assert.ok(brandingFiles.every(name => ["logo-main.svg", "logo-touch.png", "logo-big.png", "logo-192.png"].includes(name)));

  const svg = read("public/logo-main.svg");
  assert.match(svg, /^<svg\b/);
  assert.match(svg, /viewBox=/);
  assert.doesNotMatch(svg, /<image\b|data:image\//i);

  const html = read("index.html");
  assert.match(html, /rel="icon" href="\/logo-main\.svg" type="image\/svg\+xml"/);
  assert.match(html, /rel="apple-touch-icon" href="\/logo-main\.svg"/);
  assert.match(html, /rel="manifest" href="\/manifest\.webmanifest"/);
  assert.doesNotMatch(html, /\.(?:png|jpe?g|webp|ico)\b|safari-pinned-tab|msapplication-TileImage/i);

  const manifest = JSON.parse(read("public/manifest.webmanifest"));
  assert.deepEqual(manifest.icons, [
    { src: "/logo-main.svg", sizes: "any", type: "image/svg+xml", purpose: "any" },
  ]);
  const worker = read("public/sw.js");
  assert.match(worker, /addEventListener\("push"/);
  assert.match(worker, /icon: "\/logo-main\.svg"/);
  assert.match(worker, /badge: "\/logo-main\.svg"/);

  for (const file of [
    "src/app/authentication/LoginPage.jsx",
    "src/workspaces/WorkspaceLayout.jsx",
    "src/features/graph/StructurePage.jsx",
  ]) {
    const source = read(file);
    assert.match(source, /src="\/logo-main\.svg"/, file);
    assert.doesNotMatch(source, /src="\/logo\.png"/, file);
  }

  assert.match(read("Caddyfile"), /@appIcons path \/logo-main\.svg \/manifest\.webmanifest/);
  assert.doesNotMatch(read("Dockerfile"), /generate_icons|py3-pillow/);
});
