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
    const logo = page.locator(".login-logo");
    const fullLogo = await logo.boundingBox();
    await login.focus();
    await page.evaluate(() => {
      window.__fakeViewportHeight = 345;
      window.visualViewport.dispatchEvent(new Event("resize"));
    });
    await page.waitForFunction(() => document.documentElement.hasAttribute("data-app-keyboard"));
    await page.waitForFunction(() => document.querySelector(".login-screen").clientHeight === 345);
    await page.waitForFunction(() => {
      const submit = document.querySelector(".login-submit").getBoundingClientRect();
      return submit.bottom <= window.visualViewport.height - 12;
    });
    await page.locator(".login-screen").evaluate(el => Promise.all(el.getAnimations().map(a => a.finished)));
    const compactLogo = await logo.boundingBox();
    assert.ok(compactLogo.width >= 64, "The logo remains legible above the keyboard");
    assert.ok(compactLogo.width < fullLogo.width && compactLogo.width === compactLogo.height);
    const password = page.getByPlaceholder("Пароль");
    await password.focus();
    const beforeSwitch = await password.boundingBox();
    await page.evaluate(async () => {
      window.__fakeViewportHeight = 390;
      window.visualViewport.dispatchEvent(new Event("resize"));
      await new Promise(requestAnimationFrame);
      await Promise.all(document.querySelector(".login-screen").getAnimations().map(a => a.finished));
    });
    assert.deepEqual(await password.boundingBox(), beforeSwitch);
    await page.evaluate(() => {
      window.__fakeViewportHeight = 345;
      window.visualViewport.dispatchEvent(new Event("resize"));
    });
    await login.focus();
    assert.equal(await login.evaluate(el => el.closest(".login-screen").scrollTop), 0);
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
    const sidebar = page.locator(".workspace-shell > .sidebar");
    const sidebarBefore = await sidebar.boundingBox();
    await page.evaluate(() => {
      const dialog = document.createElement("dialog");
      dialog.className = "native-dialog modal";
      dialog.innerHTML = '<input /><div style="height:800px"></div><input />';
      document.body.append(dialog);
      dialog.showModal();
      dialog.firstElementChild.focus();
      Object.defineProperty(window.visualViewport, "height", { configurable: true, value: 340 });
      window.visualViewport.dispatchEvent(new Event("resize"));
    });
    await page.waitForFunction(() => document.documentElement.dataset.appKeyboard === "open");
    assert.deepEqual(await sidebar.boundingBox(), sidebarBefore, "A modal keeps the workspace header in place");
    await page.evaluate(() => document.querySelector("dialog[open]").lastElementChild.focus({ preventScroll: true }));
    await page.waitForFunction(() => {
      const dialog = document.querySelector("dialog[open]");
      return dialog.scrollTop > 0 && document.activeElement.getBoundingClientRect().bottom <= dialog.getBoundingClientRect().bottom;
    });
    await page.evaluate(() => {
      document.querySelector("dialog[open]").remove();
      delete window.visualViewport.height;
      window.visualViewport.dispatchEvent(new Event("resize"));
    });
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

test("workspace header has clear spacing and mobile dialogs stay below it", { timeout: 90000 }, async () => {
  const server = await preview({ preview: { host: "127.0.0.1", port: 22236, strictPort: true }, logLevel: "error" });
  const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH });
  try {
    for (const role of ["teacher", "admin", "student"]) {
      for (const width of [320, 390, 768, 1280]) {
        const mobile = width <= 1024;
        const page = await browser.newPage({ viewport: { width, height: 780 }, isMobile: mobile, hasTouch: mobile });
        await page.addInitScript(() => localStorage.setItem("uknowapp-auth", "1"));
        await page.route("**/api/**", route => {
          const path = new URL(route.request().url()).pathname;
          if (path === "/api/panel/me") return route.fulfill({ json: {
            id: 7, role, full_name: "Пользователь",
            permissions: role === "admin"
              ? ["structure.view", "dialogs.own", "dialogs.observe", "users.manage", "school.manage", "boards.view"]
              : role === "teacher" ? ["structure.view", "dialogs.own", "boards.view"] : ["dialogs.own", "boards.view"],
          } });
          if (path === "/api/admin/overview") return route.fulfill({ json: { teachers: [] } });
          if (path === "/api/panel/conversations" && role === "teacher") return route.fulfill({ json:
            Array.from({ length: 30 }, (_, i) => ({
              id: i + 1, type: "assignment", status: "active", unread_count: 0,
              student: { id: 100 + i, full_name: "Ученик " + (i + 1) },
              teacher: { id: 7, full_name: "Пользователь" },
            })),
          });
          return route.fulfill({ json: [] });
        });
        await page.goto(HOST + "/boards");
        await page.getByRole("button", { name: "Диалоги", exact: true }).waitFor();
        if (role === "teacher" && mobile) {
          await page.getByRole("button", { name: "Структура", exact: true }).click();
          await page.locator(".teacher-zen-student").first().waitFor();
          await page.evaluate(() => {
            // A stored offset from the old document-scrolling dialogs layout.
            sessionStorage.setItem("uknowapp-view-v1:7", JSON.stringify({
              pages: { chats: { scroll: { document: { top: 45, left: 0 }, content: { top: 30, left: 0 } } } },
            }));
            window.scrollTo(0, 300);
          });
        }
        await page.getByRole("button", { name: "Диалоги", exact: true }).click();
        await page.locator(".chat-list").waitFor();
        const geometry = await page.evaluate(async mobile => {
          await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
          const rect = el => el.getBoundingClientRect();
          const header = document.querySelector(".sidebar");
          const list = document.querySelector(".chat-list");
          const filters = list.querySelector(".chat-list-filters") || list.querySelector(".chat-items");
          const actions = [...document.querySelectorAll(mobile
            ? ".mobile-quick-actions > button" : ".topbar-actions > button")].map(rect);
          const nav = rect(header.querySelector("nav"));
          return {
            headerBottom: rect(header).bottom,
            filtersTop: rect(filters).top,
            listTop: rect(list).top,
            navTop: nav.top,
            actionBottom: Math.max(...actions.map(r => r.bottom)),
            actionGaps: actions.slice(1).map((r, i) => r.left - actions[i].right),
            actionCount: actions.length,
            documentScroll: window.scrollY,
            contentScroll: document.querySelector(".workspace-content").scrollTop,
          };
        }, mobile);
        assert.equal(geometry.actionCount, mobile ? 3 : 2);
        assert.ok(geometry.actionGaps.every(gap => gap >= 5),
          `${role} ${width}px: icon buttons have even gaps`);
        if (mobile) {
          assert.ok(geometry.navTop - geometry.actionBottom >= 6,
            `${role} ${width}px: navigation has a clear gap below quick actions`);
          assert.ok(geometry.listTop >= geometry.headerBottom && geometry.filtersTop >= geometry.headerBottom,
            `${role} ${width}px: dialogs and filters stay below the header: ${JSON.stringify(geometry)}`);
          assert.equal(geometry.documentScroll, 0);
          assert.equal(geometry.contentScroll, 0);
          if (role === "teacher") {
            await page.locator(".chat-item").first().waitFor();
            const afterScroll = await page.locator(".chat-items").evaluate(el => {
              el.scrollTop = 250;
              return { scroll: el.scrollTop, filterTop: document.querySelector(".chat-list-filters").getBoundingClientRect().top };
            });
            assert.ok(afterScroll.scroll > 0, "Long dialog lists can scroll independently");
            assert.ok(afterScroll.filterTop >= geometry.headerBottom, "Filters remain visible while dialogs scroll");
          }
        }
        if (mobile && role === "teacher") {
          const search = page.locator(".workspace-search input").first();
          assert.ok(await search.evaluate(el => parseFloat(getComputedStyle(el).fontSize) >= 16));
          await page.locator(".chat-item").first().click();
          const composer = page.locator(".chat-composer textarea");
          await composer.focus();
          await page.waitForFunction(() => document.documentElement.dataset.workspaceKeyboard === "open");
          await page.evaluate(() => {
            Object.defineProperty(window.visualViewport, "height", { configurable: true, value: 350 });
            window.visualViewport.dispatchEvent(new Event("resize"));
          });
          await page.waitForFunction(() => {
            const box = document.querySelector(".chat-composer textarea").getBoundingClientRect();
            return box.top >= 0 && box.bottom <= 350;
          });
        }
        await page.close();
      }
    }
  } finally {
    await browser.close();
    await new Promise((resolve, reject) => server.httpServer.close(error => error ? reject(error) : resolve()));
  }
});
