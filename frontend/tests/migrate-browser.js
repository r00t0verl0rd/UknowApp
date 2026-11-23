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
    // После восстановления backend перезапускается: прокси может временно отвечать 502.
    let result;
    for (let attempt = 0; attempt < 60; attempt++) {
      try {
        result = await api.post(url + "/api/auth/login", {
          data: { username: "migration-admin", password: process.env.ADMIN_PASSWORD },
        });
        if (result.status() === 200) break;
        if (![502, 503, 504].includes(result.status())) {
          assert.equal(result.status(), 200);
        }
      } catch (error) {
        if (attempt === 59) throw error;
      }
      await new Promise(resolve => setTimeout(resolve, 1000));
    }
    assert.equal(result?.status(), 200);
    await page.goto(url + "/additional");
    await page.evaluate(() => localStorage.setItem("uknowapp-auth", "1"));
    await page.reload();
  }
  await login();
  if (process.argv[2] === "export") {
    // Проверяем перенос обоих типов переписок через API без зависимости от кнопок интерфейса.
    const usersResponse = await api.get(url + "/api/admin/users");
    assert.equal(usersResponse.status(), 200);
    const [teacher] = (await usersResponse.json()).filter(user => user.role === "teacher");
    assert.ok(teacher, "Migration fixture must contain a teacher");
    const personalResponse = await api.post(url + "/api/panel/personal-conversations", {
      data: { user_id: teacher.id },
    });
    assert.equal(personalResponse.status(), 201);
    const personal = await personalResponse.json();
    const personalMessageResponse = await api.post(
      url + "/api/panel/personal-conversations/" + personal.id + "/messages",
      { data: { text: "migration personal lesson" } },
    );
    assert.equal(personalMessageResponse.status(), 201);
    await page.goto(url + "/additional");
    const downloading = page.waitForEvent("download");
    await page.getByRole("button", { name: "Скачать полную резервную копию" }).click();
    await (await downloading).saveAs(archive);
    assert.ok((await stat(archive)).size > 22 * 1024 * 1024);
  } else {
    assert.deepEqual(await (await api.get(url + "/api/panel/conversations")).json(), []);
    const uploading = page.waitForResponse(res =>
      res.url().endsWith("/api/admin/data/full") && res.request().method() === "POST");
    await page.locator('input[accept=".zip"]').setInputFiles(archive);
    const confirmation = page.getByRole("alertdialog", { name: "Восстановить резервную копию?" });
    await confirmation.getByRole("button", { name: "Восстановить", exact: true }).click();
    assert.equal((await uploading).status(), 202);
    // Восстановление базы заменяет сессию администратора.
    await page.getByRole("button", { name: "Войти" }).waitFor({ timeout: 120000 });
    await login();
    // Проверяем результат переноса по серверному статусу, а не по исчезающему уведомлению.
    const restoreResponse = await api.get(url + "/api/admin/data/restore-status");
    assert.equal(restoreResponse.status(), 200);
    assert.equal((await restoreResponse.json()).restore?.status, "completed");
    const personalChatsResponse = await api.get(url + "/api/panel/personal-conversations");
    assert.equal(personalChatsResponse.status(), 200);
    const personalChats = await personalChatsResponse.json();
    assert.equal(personalChats.length, 1);
    assert.equal(personalChats[0].participant.role, "teacher");
    const personalMessagesResponse = await api.get(
      url + "/api/panel/personal-conversations/" + personalChats[0].id + "/messages",
    );
    assert.equal(personalMessagesResponse.status(), 200);
    assert.ok((await personalMessagesResponse.json()).some(row => row.text === "migration personal lesson"));
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
    assert.equal((await api.post(history, { data: { text: "after migration" } })).status(), 201);
    assert.ok((await (await api.get(history)).json()).some(row => row.text === "after migration"));
  }
} finally {
  await browser.close();
}
