/**
 * Проверка объёма CSS и кандидатов на удаление.
 * Учитывает динамические модификаторы размера кнопок IconButton.
 * Не удаляет классы автоматически: всё остальное требует ручной проверки.
 */
import fs from "node:fs";
import path from "node:path";
import postcss from "postcss";
import { compile } from "sass";

const root = path.resolve(import.meta.dirname, "..");
const cssDir = path.join(root, "src/shared/styles");
const sourceExtensions = new Set([".jsx", ".js", ".html"]);
const sources = [];
const walk = directory => {
  for (const item of fs.readdirSync(directory, { withFileTypes: true })) {
    const file = path.join(directory, item.name);
    if (item.isDirectory()) walk(file);
    else if (sourceExtensions.has(path.extname(file)) && !file.endsWith(".test.js")) {
      sources.push(fs.readFileSync(file, "utf8"));
    }
  }
};
walk(path.join(root, "src"));
sources.push(fs.readFileSync(path.join(root, "index.html"), "utf8"));
const sourceText = sources.join("\n");
const sourceTokens = new Set(sourceText.match(/[\w-]+/g));

// IconButton builds its size class from the size prop. Do not mistake a
// dynamically constructed, actually used modifier for an orphan CSS selector.
const dynamicIconSizes = new Set(
  [...sourceText.matchAll(/<IconButton\b[^>]*\bsize=["']([\w-]+)["']/g)].map(match => match[1])
);
const dynamicClasses = new Set([...dynamicIconSizes].map(size => `ui-icon-button--${size}`));

let rules = 0;
let declarations = 0;
let important = 0;
let totalBytes = 0;
const candidates = new Map();
const selectorUses = new Map();
const repeatedClasses = [];

for (const file of fs.readdirSync(cssDir).filter(name => name.endsWith(".scss"))) {
  const source = fs.readFileSync(path.join(cssDir, file), "utf8");
  totalBytes += Buffer.byteLength(source);
  const ast = postcss.parse(source, { from: file });
  ast.walkRules(rule => {
    rules++;
    if (/\.([A-Za-z_][\w-]*)\.\1(?![\w-])/.test(rule.selector)) {
      repeatedClasses.push(`${file}:${rule.source.start.line} ${rule.selector}`);
    }
    // У вложенных CSS-правил считаем декларации один раз.
    for (const decl of rule.nodes ?? []) {
      if (decl.type !== "decl") continue;
      declarations++;
      if (decl.important) important++;
    }
    for (const [, className] of rule.selector.matchAll(/\.([A-Za-z_][\w-]*)/g)) {
      selectorUses.set(className, (selectorUses.get(className) ?? 0) + 1);
      // Буквальное отсутствие в JSX/JS ещё не доказывает, что класс не используется.
      if (sourceTokens.has(className) || dynamicClasses.has(className)) continue;
      const found = candidates.get(className) ?? new Set();
      found.add(file);
      candidates.set(className, found);
    }
  });
}

const compiled = postcss.parse(compile(path.join(cssDir, "index.scss")).css);
const ruleKeys = new Set();
let repeatedSelectorBlocks = 0;
compiled.walkRules(rule => {
  const scope = [];
  for (let parent = rule.parent; parent.type === "atrule"; parent = parent.parent) {
    scope.unshift([parent.name, parent.params]);
  }
  const selectors = postcss.list.comma(rule.selector).sort();
  const key = JSON.stringify([scope, selectors]);
  if (ruleKeys.has(key)) repeatedSelectorBlocks++;
  ruleKeys.add(key);
});

console.log("Сводка CSS:", JSON.stringify({
  files: fs.readdirSync(cssDir).filter(name => name.endsWith(".scss")).length,
  bytes: totalBytes, rules, declarations, important, repeatedSelectorBlocks,
  uniqueClasses: selectorUses.size,
  unconfirmedClasses: candidates.size,
}));
console.log("Кандидаты для ручной проверки (класс и файлы):");
for (const [name, files] of [...candidates].sort((a, b) => (
  (selectorUses.get(b[0]) ?? 0) - (selectorUses.get(a[0]) ?? 0)
)).slice(0, 100)) {
  console.log(name + "\t" + [...files].join(", "));
}

const tokenFile = fs.readFileSync(path.join(cssDir, "tokens.scss"), "utf8");
const allCss = fs.readdirSync(cssDir).filter(name => name.endsWith(".scss"))
  .map(name => fs.readFileSync(path.join(cssDir, name), "utf8")).join("\n");
const definitions = [...tokenFile.matchAll(/^\s*(--[\w-]+)\s*:/gm)].map(match => match[1]);
const referencedTokens = new Set([...allCss.matchAll(/var\(\s*(--[\w-]+)/g)]
  .map(match => match[1]));
const unusedTokens = [...new Set(definitions)]
  .filter(name => !referencedTokens.has(name) && !sourceText.includes(name));
console.log("Переменные без использования в CSS и JS:", JSON.stringify(unusedTokens));

// Новые неиспользуемые токены не должны накапливаться в проекте.
if (unusedTokens.length) {
  console.error("Неиспользуемые CSS-переменные требуют удаления или применения.");
  process.exitCode = 1;
}
