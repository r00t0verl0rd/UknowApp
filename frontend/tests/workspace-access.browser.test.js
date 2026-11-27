import assert from "node:assert/strict";
import test from "node:test";
import { chromium } from "playwright";
import { preview } from "vite";

test("workspace stays closed until the server confirms the role and redirects a student from /users", async () => {
  const server = await preview({ preview: { host: "127.0.0.1", port: 22223, strictPort: true }, logLevel: "error" });
  const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH });
  try {
    const page = await browser.newPage();
    await page.goto("http://127.0.0.1:22223");
    await page.evaluate(() => localStorage.setItem("uknowapp-auth", "1"));
    let started;
    const pending = new Promise(resolve => { started = resolve; });
    let confirm;
    const profile = new Promise(resolve => { confirm = resolve; });
    const requests = [];
    await page.route("**/api/**", async route => {
      const path = new URL(route.request().url()).pathname;
      requests.push(path);
      if (path === "/api/panel/me") {
        started();
        await profile;
        return route.fulfill({ json: { id: 12, role: "student", full_name: "Ученик", permissions: ["dialogs.own", "boards.view"] } });
      }
      return route.fulfill({ json: [] });
    });
    await page.goto("http://127.0.0.1:22223/users", { waitUntil: "domcontentloaded" });
    await pending;
    assert.deepEqual(requests, ["/api/panel/me"]);
    assert.equal(await page.getByRole("button", { name: "Пользователи" }).count(), 0);
    const stylesheetText = () => page.evaluate(() => [...document.styleSheets]
      .flatMap(sheet => [...sheet.cssRules].map(rule => rule.cssText)).join("\n"));
    const beforeAuth = await stylesheetText();
    assert.doesNotMatch(beforeAuth, /\.data-stat-card\b|\.user-info-login\b|\.teacher-zen-stage\b/);
    confirm();
    await page.waitForURL("**/dialogs");
    await page.getByRole("button", { name: "Доски", exact: true }).click();
    await page.getByRole("heading", { name: "Раздел в разработке." }).waitFor();
    assert.equal(
      await page.getByText("Здесь появится удобное пространство для совместной работы, материалов и визуальных задач.").count(),
      1,
    );
    assert.equal(await page.getByRole("button", { name: "Структура", exact: true }).count(), 0);
    assert.ok(requests.every(path => !path.startsWith("/api/admin/")));
    const studentCss = await stylesheetText();
    assert.match(studentCss, /\.boards-placeholder\b/);
    assert.doesNotMatch(studentCss, /\.data-stat-card\b|\.user-info-login\b|\.teacher-zen-stage\b|\.restore-flow-progress-bar\b/);
    // Истёкшая сессия возвращает ко входу; временный сбой не сбрасывает экран.
    await page.route("**/api/panel/me", route => route.fulfill({ status: 401, json: {} }));
    await page.reload();
    await page.getByRole("button", { name: "Войти", exact: true }).waitFor();
    assert.equal(await page.getByRole("button", { name: "Доски", exact: true }).count(), 0);
  } finally {
    await browser.close();
    await new Promise((resolve, reject) => server.httpServer.close(error => error ? reject(error) : resolve()));
  }
});
