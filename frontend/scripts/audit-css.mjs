/**
 * Проверка объёма CSS и кандидатов на удаление.
 * Не удаляет стили: динамические классы нужно проверять вручную.
 */
import fs from "node:fs";
import path from "node:path";
import postcss from "postcss";

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

let rules = 0;
let declarations = 0;
let important = 0;
let totalBytes = 0;
const candidates = new Map();
const selectorUses = new Map();

for (const file of fs.readdirSync(cssDir).filter(name => name.endsWith(".css"))) {
  const source = fs.readFileSync(path.join(cssDir, file), "utf8");
  totalBytes += Buffer.byteLength(source);
  const ast = postcss.parse(source, { from: file });
  ast.walkRules(rule => {
    rules++;
    rule.walkDecls(decl => {
      declarations++;
      if (decl.important) important++;
    });
    for (const [, className] of rule.selector.matchAll(/\.([A-Za-z_][\w-]*)/g)) {
      selectorUses.set(className, (selectorUses.get(className) ?? 0) + 1);
      // Буквальное отсутствие в JSX/JS ещё не доказывает, что класс не используется.
      if (sourceText.includes(className)) continue;
      const found = candidates.get(className) ?? new Set();
      found.add(file);
      candidates.set(className, found);
    }
  });
}

console.log("Сводка CSS:", JSON.stringify({
  files: fs.readdirSync(cssDir).filter(name => name.endsWith(".css")).length,
  bytes: totalBytes, rules, declarations, important,
  uniqueClasses: selectorUses.size,
  unconfirmedClasses: candidates.size,
}));
console.log("Кандидаты для ручной проверки (класс и файлы):");
for (const [name, files] of [...candidates].sort((a, b) => (
  (selectorUses.get(b[0]) ?? 0) - (selectorUses.get(a[0]) ?? 0)
)).slice(0, 100)) {
  console.log(name + "\t" + [...files].join(", "));
}

const tokenFile = fs.readFileSync(path.join(cssDir, "tokens.css"), "utf8");
const allCss = fs.readdirSync(cssDir).filter(name => name.endsWith(".css"))
  .map(name => fs.readFileSync(path.join(cssDir, name), "utf8")).join("\n");
const definitions = [...tokenFile.matchAll(/^\s*(--[\w-]+)\s*:/gm)].map(match => match[1]);
const unusedTokens = [...new Set(definitions)].filter(name => {
  const expression = new RegExp("var\\\\(\\\\s*" + name + "(?![\\\\w-])");
  return !expression.test(allCss) && !sourceText.includes(name);
});
console.log("Переменные без использования в CSS и JS:", JSON.stringify(unusedTokens));
