import assert from "node:assert/strict";
import test from "node:test";
import { chromium } from "playwright";
import { preview } from "vite";

const HOST = "http://127.0.0.1:22236";

test("keyboard-aware login, workspace dialogs and consistent touch buttons", { timeout: 50000 }, async () => {
  const server = await preview({ preview: { host: "127.0.0.1", port: 22236, strictPort: true }, logLevel: "error" });
  const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH });
  try {
    const page = await browser.newPage({ viewport: { width: 390, height: 780 }, isMobile: true, hasTouch: true });
    await page.route("**/api/**", route => {
      const path = new URL(route.request().url()).pathname;
      if (path === "/api/panel/me") return route.fulfill({ json: {
        id: 1, full_name: "Администратор", role: "admin",
        permissions: ["structure.view", "dialogs.own", "users.manage", "school.manage", "dialogs.observe"],
      } });
      if (path === "/api/admin/overview") return route.fulfill({ json: { teachers: [] } });
      if (path === "/api/panel/conversations" || path === "/api/panel/personal-conversations") {
        return route.fulfill({ json: [] });
      }
      return route.fulfill({ json: [] });
    });

    await page.goto(HOST);
    const login = page.getByRole("textbox", { name: "Логин" });
    await login.waitFor({ state: "visible" });
    await page.evaluate(() => {
      window.__fakeViewportHeight = window.visualViewport.height;
      Object.defineProperty(window.visualViewport, "height", {
        configurable: true, get() { return window.__fakeViewportHeight; },
      });
    });
    await login.focus();
    await page.evaluate(() => {
      window.__fakeViewportHeight = 345;
      window.visualViewport.dispatchEvent(new Event("resize"));
    });
    await page.waitForFunction(() => document.documentElement.hasAttribute("data-app-keyboard"));
    assert.equal(await page.locator(".login-screen").evaluate(el => Math.round(el.getBoundingClientRect().height)), 345);
    const loginRect = await login.evaluate(el => {
      const { top, bottom } = el.getBoundingClientRect();
      return { top, bottom };
    });
    assert.ok(loginRect.top >= 0 && loginRect.bottom <= 345,
      "Login input remains reachable within the keyboard-visible viewport");

    await page.evaluate(() => {
      const dialog = document.createElement("dialog");
      dialog.className = "modal native-dialog";
      dialog.innerHTML = '<input aria-label="Модальное поле" />';
      document.body.append(dialog);
      dialog.showModal();
      dialog.querySelector("input").focus();
    });
    await page.waitForFunction(() => {
      const dialog = document.querySelector("dialog.native-dialog");
      return dialog && Math.round(dialog.getBoundingClientRect().top) >= 0 &&
        dialog.getBoundingClientRect().bottom <= 345;
    });
    await page.evaluate(() => {
      document.querySelector("dialog.native-dialog")?.remove();
      document.activeElement?.blur();
      window.__fakeViewportHeight = window.innerHeight;
      window.visualViewport.dispatchEvent(new Event("resize"));
    });
    await page.waitForFunction(() => !document.documentElement.hasAttribute("data-app-keyboard"));

    await page.evaluate(() => localStorage.setItem("uknowapp-auth", "1"));
    await page.goto(HOST);
    const signOut = page.getByRole("button", { name: "Выйти" });
    await signOut.waitFor({ state: "visible" });
    const iconBox = await signOut.evaluate(el => el.getBoundingClientRect().width);
    assert.ok(iconBox >= 36, "Mobile header icon buttons have adequate touch targets");
    await signOut.click();
    const confirm = page.getByRole("alertdialog", { name: "Выйти из аккаунта?" });
    await confirm.waitFor({ state: "visible" });
    const dimensions = await confirm.getByRole("button", { name: "Нет" }).evaluate(el => {
      const b = el.getBoundingClientRect();
      return { width: b.width, height: b.height, fontSize: parseFloat(getComputedStyle(el).fontSize) };
    });
    assert.ok(dimensions.width >= 100 && dimensions.height >= 50 && dimensions.fontSize >= 15,
      `Confirmation button is usable: ${JSON.stringify(dimensions)}`);
    assert.ok((await confirm.getByRole("button", { name: "Да" }).boundingBox()).width >= 100);
    await confirm.getByRole("button", { name: "Нет" }).click();
    assert.equal(await confirm.count(), 0);
  } finally {
    await browser.close();
    await new Promise((resolve, reject) => server.httpServer.close(error => error ? reject(error) : resolve()));
  }
});
