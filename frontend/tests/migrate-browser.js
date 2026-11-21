import assert from "node:assert/strict";
import { stat } from "node:fs/promises";
import { chromium } from "playwright";

const url = "http://localhost";
const archive = process.env.MIGRATION_ARCHIVE;
const browser = await chromium.launch();
try {
  const page = await browser.newPage();
  const api = page.context().request;
  async function login() {
    const result = await api.post(url + "/api/auth/login", {
      data: { username: "migration-admin", password: process.env.ADMIN_PASSWORD },
    });
    assert.equal(result.status(), 200);
    await page.goto(url + "/additional");
    await page.evaluate(() => localStorage.setItem("uknowapp-auth", "1"));
    await page.reload();
  }
  await login();
  if (process.argv[2] === "export") {
    const downloading = page.waitForEvent("download");
    await page.getByRole("button", { name: "Скачать полную резервную копию" }).click();
    await (await downloading).saveAs(archive);
    assert.ok((await stat(archive)).size > 22 * 1024 * 1024);
  } else {
    assert.deepEqual(await (await api.get(url + "/api/panel/conversations")).json(), []);
    page.once("dialog", dialog => dialog.accept());
    const uploading = page.waitForResponse(res =>
      res.url().endsWith("/api/admin/data/full") && res.request().method() === "POST");
    await page.locator('input[accept=".zip"]').setInputFiles(archive);
    assert.equal((await uploading).status(), 202);
    // Restoring the source database replaces the target admin session.
    await page.getByRole("button", { name: "Войти" }).waitFor({ timeout: 120000 });
    await login();
    await page.getByText("Полная копия восстановлена.", { exact: false }).waitFor();
    const [chat] = await (await api.get(url + "/api/panel/conversations")).json();
    const history = url + "/api/panel/conversations/" + chat.id + "/messages";
    const [message] = await (await api.get(history)).json();
    assert.equal(message.text, "migration lesson");
    const duration = await page.evaluate(id => new Promise((resolve, reject) => {
      const audio = new Audio("/api/panel/messages/" + id + "/media");
      audio.onloadedmetadata = () => resolve(audio.duration);
      audio.onerror = () => reject(new Error("Restored audio could not be decoded"));
    }), message.id);
    assert.equal(duration, 1);
    const personal = await api.post(url + "/api/panel/personal-conversations", { data: { user_id: chat.teacher.id } });
    assert.equal(personal.status(), 201);
    const messages = url + "/api/panel/personal-conversations/" + (await personal.json()).id + "/messages";
    assert.equal((await api.post(messages, { data: { text: "after migration" } })).status(), 201);
    assert.ok((await (await api.get(messages)).json()).some(row => row.text === "after migration"));
  }
} finally {
  await browser.close();
}
