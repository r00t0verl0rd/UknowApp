import assert from "node:assert/strict";
import test from "node:test";
import { chromium } from "playwright";
import { preview } from "vite";

const HOST = "http://127.0.0.1:22225";
const RESTORE_ID = "restore-flow-browser-test";

test("backup restore explains the restart, asks before re-login and shows verified result", { timeout: 45000 }, async () => {
  const server = await preview({
    preview: { host: "127.0.0.1", port: 22225, strictPort: true },
    logLevel: "error",
  });
  const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH });
  try {
    const page = await browser.newPage();
    let invalidated = false;
    let accepted = false;
    let statusChecks = 0;
    await page.route("**/api/**", route => {
      const url = new URL(route.request().url());
      const path = url.pathname;
      if (path === "/api/auth/login") {
        invalidated = false;
        return route.fulfill({ status: 200, json: { ok: true } });
      }
      if (path === "/api/panel/me") {
        if (invalidated) return route.fulfill({ status: 401, json: { detail: "Session expired" } });
        return route.fulfill({ json: {
          id: 1, full_name: "Администратор", role: "admin",
          permissions: ["structure.view", "dialogs.own", "users.manage", "boards.view", "school.manage", "dialogs.observe"],
        } });
      }
      if (path === "/api/admin/data/full" && route.request().method() === "POST") {
        accepted = true;
        invalidated = true;
        return route.fulfill({ status: 202, json: {
          ok: true, restore_id: RESTORE_ID, automatic_restart: true, restart_required: true,
        } });
      }
      if (path === "/api/admin/data/restore-status") {
        statusChecks += 1;
        if (invalidated) return route.fulfill({ status: 401, json: { detail: "Please log in again" } });
        return route.fulfill({ json: { restore: accepted
          ? { id: RESTORE_ID, status: "completed" }
          : null } });
      }
      if (path === "/api/admin/data/stats") {
        return route.fulfill({ json: { restore: null, users: 0, teachers: 0, students: 0 } });
      }
      if (path === "/api/admin/overview") return route.fulfill({ json: { teachers: [] } });
      return route.fulfill({ json: [] });
    });

    await page.goto(HOST);
    await page.evaluate(() => localStorage.setItem("uknowapp-auth", "1"));
    await page.goto(HOST + "/additional");
    await page.locator('input[type="file"][accept=".zip"]').setInputFiles({
      name: "example-backup.zip", mimeType: "application/zip",
      buffer: Buffer.from("test fixture, server upload is mocked"),
    });
    await page.getByRole("alertdialog", { name: "Восстановить резервную копию?" })
      .getByRole("button", { name: "Восстановить", exact: true }).click();

    await page.getByRole("progressbar", { name: "Ход восстановления резервной копии" }).waitFor();
    await page.getByRole("alertdialog", { name: "Требуется повторный вход" }).waitFor({ timeout: 12000 });
    assert.equal(accepted, true);
    assert.ok(statusChecks > 0);
    assert.ok(page.url().endsWith("/additional"), "The page must not silently redirect to login");

    await page.getByRole("button", { name: "Завершить сеанс и войти снова" }).click();
    await page.getByText("Сессия завершена после восстановления").waitFor({ timeout: 10000 });
    assert.equal(await page.evaluate(() => localStorage.getItem("uknowapp-auth")), null);
    await page.getByLabel("Логин").fill("new-admin");
    await page.getByLabel("Пароль").fill("restored-password");
    await page.getByRole("button", { name: "Войти" }).click();
    await page.getByRole("alertdialog", { name: "Восстановление завершено" }).waitFor({ timeout: 12000 });
    await page.getByRole("button", { name: "Понятно" }).click();
    assert.equal(await page.getByRole("alertdialog", { name: "Восстановление завершено" }).count(), 0);
  } finally {
    await browser.close();
    await new Promise((resolve, reject) => server.httpServer.close(error => error ? reject(error) : resolve()));
  }
});
