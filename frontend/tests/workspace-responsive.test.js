import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

const frontend = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const css = readFileSync(path.join(frontend, "src/shared/styles/workspace-scroll.css"), "utf8");
const standalone = readFileSync(path.join(frontend, "src/shared/styles/standalone.css"), "utf8");
const layout = readFileSync(path.join(frontend, "src/workspaces/WorkspaceLayout.jsx"), "utf8");

test("mobile and desktop use one theme surface for the workspace", () => {
  assert.match(css, /--workspace-background:\s*var\(--surface\)/);
  assert.match(css, /:root\[data-theme\]:has\(\.workspace-shell\)\s*\{\s*background:\s*var\(--workspace-background\)\s*!important/);
  assert.match(css, /\.workspace-shell\s*>\s*\.sidebar,[\s\S]*?\.workspace-shell\s*>\s*\.content\s*>\s*\.workspace-content\s*\{\s*background:\s*transparent\s*!important/);
  assert.doesNotMatch(css, /\.workspace-shell\s*>\s*\.content\s*\{\s*background:\s*var\(--canvas\)/);
  assert.match(standalone, /background:\s*var\(--workspace-background\)\s*!important/);
});

test("responsive layout keeps the same two main blocks and Safari safe areas", () => {
  assert.match(layout, /<aside className="sidebar">/);
  assert.match(layout, /<main className="content">/);
  assert.match(layout, /className=\{"workspace-content"/);
  assert.match(css, /@media\s*\(max-width:\s*1024px\)/);
  assert.match(css, /@media\s*\(max-width:\s*1024px\)\s*and\s*\(display-mode:\s*browser\)/);
  assert.match(css, /height:\s*calc\(100lvh\s*\+\s*var\(--workspace-chrome-bottom\)\)/);
  assert.match(css, /--workspace-viewport-height/);
  assert.match(css, /env\(safe-area-inset-bottom/);
});
