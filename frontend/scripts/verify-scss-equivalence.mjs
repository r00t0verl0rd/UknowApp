/**
 * Verify that a refactor changes only SCSS source, not the browser's compiled CSS.
 * Usage: node scripts/verify-scss-equivalence.mjs <base-commit-sha>
 */
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { compile } from "sass";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const repository = path.resolve(root, "..");
const base = process.argv[2];
if (!base || !/^[0-9a-f]{40}$/.test(base)) {
  console.error("Pass the 40-character base commit SHA.");
  process.exit(2);
}
const styles = "frontend/src/shared/styles/";
const temporary = mkdtempSync(path.join(tmpdir(), "uknow-scss-"));
try {
  const baseline = path.join(temporary, "styles");
  mkdirSync(baseline);
  const fileNames = execFileSync(
    "git", ["ls-tree", "-r", "--name-only", base, "--", styles],
    { cwd: repository, encoding: "utf8" }
  ).trim().split("\n").filter(name => name.endsWith(".scss"));
  for (const file of fileNames) {
    const content = execFileSync("git", ["show", `${base}:${file}`], {
      cwd: repository, encoding: "utf8", maxBuffer: 1024 * 1024,
    });
    const output = path.join(baseline, file.slice(styles.length));
    mkdirSync(path.dirname(output), { recursive: true });
    writeFileSync(output, content);
  }
  const oldCss = compile(path.join(baseline, "index.scss"), { style: "compressed" }).css;
  const newCss = compile(path.join(root, "src/shared/styles/index.scss"), {
    style: "compressed",
  }).css;
  const position = [...oldCss].findIndex((character, i) => character !== newCss[i]);
  if (oldCss !== newCss) {
    const index = position === -1 ? Math.min(oldCss.length, newCss.length) : position;
    console.error("Compiled CSS differs at character", index);
    console.error("base:", JSON.stringify(oldCss.slice(Math.max(0, index - 70), index + 100)));
    console.error("head:", JSON.stringify(newCss.slice(Math.max(0, index - 70), index + 100)));
  }
  assert.equal(newCss, oldCss, "SCSS refactor changed compiled CSS");
  console.log(`Compiled CSS is byte-identical (${newCss.length} characters).`);
} finally {
  rmSync(temporary, { recursive: true, force: true });
}
