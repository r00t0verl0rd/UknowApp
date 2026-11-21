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
  if (process.argv[2] === "export") {
    // Проверяем готовый HTML до первого отображения React и стилей.
    const beforeReact = await browser.newPage();
    await beforeReact.route("**/assets/**", route => route.abort());
    await beforeReact.goto(url);
    assert.equal(await beforeReact.locator("body").evaluate(node => getComputedStyle(node).backgroundColor), "rgb(23, 27, 37)");
    await beforeReact.addInitScript(() => localStorage.setItem("uknowapp-theme-v2", "light"));
    await beforeReact.reload();
    assert.equal(await beforeReact.locator("body").evaluate(node => getComputedStyle(node).backgroundColor), "rgb(247, 246, 251)");
    await beforeReact.close();
    await page.goto(url);
    await page.getByRole("button", { name: "Войти" }).click();
    const alert = page.getByRole("alert");
    await alert.getByText("Введите логин").waitFor();
    const close = alert.getByRole("button", { name: "Закрыть уведомление об ошибке" });
    for (const width of [390, 1280]) {
      await page.setViewportSize({ width, height: 800 });
      for (const theme of ["light", "dark-soft"]) {
        await page.evaluate(value => { document.documentElement.dataset.theme = value; }, theme);
        const icon = await close.locator("svg").boundingBox();
        const target = await close.boundingBox();
        assert.equal(icon.width, 14);
        assert.equal(icon.height, 14);
        assert.ok(target.width >= 40 && target.height >= 40);
      }
    }
    await alert.getByRole("button", { name: "Закрыть уведомление об ошибке" }).click();
    await alert.waitFor({ state: "hidden" });
  }
  await login();
  if (process.argv[2] === "export") {
    await page.goto(url + "/dialogs");
    await page.getByRole("button", { name: "Личные" }).click();
    const [teacher] = (await (await api.get(url + "/api/admin/users")).json()).filter(user => user.role === "teacher");
    const dialog = page.getByRole("dialog", { name: "Создать диалог" });
    for (const width of [320, 390, 768, 1280]) {
      await page.setViewportSize({ width, height: 800 });
      const nav = page.getByRole("navigation", { name: "Основная навигация" });
      if (width <= 760) {
        const tops = await nav.getByRole("button").evaluateAll(items => items.map(item => item.offsetTop));
        assert.equal(new Set(tops).size, 1);
      }
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    }
    await page.setViewportSize({ width: 390, height: 800 });
    async function openPersonal() {
      await page.getByRole("button", { name: "Новый диалог" }).click();
      await dialog.getByLabel("Участник").selectOption(String(teacher.id));
      await dialog.getByRole("button", { name: "Создать диалог" }).click();
      await dialog.waitFor({ state: "hidden" });
    }
    const createUrl = url + "/api/panel/personal-conversations";
    await page.route(createUrl, route => route.request().method() === "POST"
      ? route.fulfill({ status: 503, json: { detail: "Временно недоступно" } })
      : route.continue());
    await page.getByRole("button", { name: "Новый диалог" }).click();
    await dialog.getByLabel("Участник").selectOption(String(teacher.id));
    await dialog.getByRole("button", { name: "Создать диалог" }).click();
    const alert = page.getByRole("alert").filter({ hasText: "Временно недоступно" });
    await alert.getByRole("button", { name: "Закрыть уведомление об ошибке" }).click();
    assert.equal(await dialog.getByLabel("Участник").inputValue(), String(teacher.id));
    await page.unroute(createUrl);
    await dialog.getByRole("button", { name: "Создать диалог" }).click();
    await dialog.waitFor({ state: "hidden" });
    await page.getByPlaceholder("Личное сообщение…").fill("Проверка личного диалога");
    await page.getByRole("button", { name: "Отправить сообщение" }).click();
    const message = page.locator(".messages").getByText("Проверка личного диалога", { exact: true });
    await message.waitFor();
    assert.equal(await page.locator(".toast").filter({ hasText: "Сообщение отправлено" }).count(), 0);
    const trash = message.locator("..").getByRole("button", { name: "Удалить своё сообщение" });
    assert.equal((await trash.locator("svg").boundingBox()).width, 12);
    await trash.click();
    await page.getByRole("alertdialog").getByRole("button", { name: "Отмена" }).click();
    await page.getByRole('button', { name: 'Назад к списку диалогов' }).click();
    await openPersonal();
    await message.waitFor();
    const personal = await (await api.get(url + "/api/panel/personal-conversations")).json();
    assert.deepEqual(personal.map(chat => chat.participant.id), [teacher.id]);
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto(url + "/additional");
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
    // Восстановление базы заменяет сессию администратора.
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
    assert.equal((await api.post(history, { data: { text: "after migration" } })).status(), 201);
    assert.ok((await (await api.get(history)).json()).some(row => row.text === "after migration"));
  }
} finally {
  await browser.close();
}
