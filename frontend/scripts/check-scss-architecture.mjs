/**
 * Fast, dependency-free checks for the SCSS ownership structure.
 * Full CSS-equivalence checks and visual review are separate steps.
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const styles = path.join(root, "src/shared/styles");
const files = [];
const errors = [];
const walk = directory => {
  for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
    const filename = path.join(directory, entry.name);
    if (entry.isDirectory()) walk(filename);
    else if (filename.endsWith(".scss")) files.push(filename);
  }
};
walk(styles);

const entrypoints = new Set(["index.scss", "core/_primitives.scss"]);
const owners = new Set(["core", "components", "features", "workspace"]);
const sourceFiles = new Set(files.map(file => path.relative(styles, file).replaceAll(path.sep, "/")));
const resolveUse = (file, relative) => {
  const target = path.resolve(path.dirname(file), relative);
  return [target + ".scss", path.join(path.dirname(target), "_" + path.basename(target) + ".scss")]
    .some(candidate => fs.existsSync(candidate));
};

const imported = new Set();
const index = fs.readFileSync(path.join(styles, "index.scss"), "utf8");
for (const [, relative] of index.matchAll(/^@use\s+["']\.\/([^"']+)["'];/gm)) {
  const file = relative + ".scss";
  if (imported.has(file)) errors.push(`Repeated index import: ${file}`);
  imported.add(file);
  if (!sourceFiles.has(file)) errors.push(`Index imports missing file: ${file}`);
}
for (const file of files) {
  const name = path.relative(styles, file).replaceAll(path.sep, "/");
  const source = fs.readFileSync(file, "utf8");
  if (!entrypoints.has(name) && !owners.has(name.split("/")[0])) {
    errors.push(`Choose a component, feature, workspace or core owner for ${name}`);
  }
  if (!entrypoints.has(name) && !imported.has(name)) {
    errors.push(`SCSS module absent from index.scss: ${name}`);
  }
  if (/!important\b/.test(source)) errors.push(`Avoid !important: ${name}`);
  if (/^\s*@import\s/m.test(source)) errors.push(`Use @use, not @import: ${name}`);
  for (const [i, line] of source.split("\n").entries()) {
    if (line.length > 220) errors.push(`Minified/overlong line: ${name}:${i + 1}`);
  }
  for (const [, relative] of source.matchAll(/@use\s+["'](\.[^"']+)["'];/g)) {
    if (!resolveUse(file, relative)) {
      errors.push(`Unresolved @use in ${name}: ${relative}`);
    }
  }
}
if (errors.length) {
  for (const error of errors) console.error(error);
  process.exitCode = 1;
} else {
  console.log(`SCSS architecture OK: ${files.length} files, ${imported.size} indexed modules; no !important or minified lines.`);
}
