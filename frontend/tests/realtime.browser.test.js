import assert from "node:assert/strict";
import { createServer } from "node:http";
import { spawn } from "node:child_process";
import { setTimeout as delay } from "node:timers/promises";
import test from "node:test";
import { chromium } from "playwright";

const API_PORT = 8000;
const APP_PORT = 22222;
const APP_URL = `http://127.0.0.1:${APP_PORT}`;
const personalChat = {
  id: 5,
  type: "personal",
  participant: { id: 17, full_name: "Учитель", role: "teacher" },
  title: "Учитель",
  created_at: "2026-11-21T10:00:00+00:00",
  unread_count: 1,
};

function waitFor(check, timeout = 12000) {
  const started = Date.now();
  return new Promise((resolve, reject) => {
    const poll = async () => {
      try {
        if (await check()) return resolve();
      } catch { /* Ожидаем готовности браузера или сервера. */ }
      if (Date.now() - started > timeout) return reject(new Error("Timed out waiting for browser integration condition"));
      setTimeout(poll, 40);
    };
    void poll();
  });
}

test("global SSE updates real counters across tabs and replays missed events", { timeout: 60000 }, async () => {
  const streams = new Set();
  const pendingPersonalResponses = [];
  const eventLog = [];
  const lastEventIds = [];
  let maxActiveStreams = 0;
  let inboxRequests = 0;
  let personalRequests = 0;
  let syncRequests = 0;
  let latestUnread = personalChat.unread_count;
  let syncNewMessages = [];
  let apiServer;
  let vite;
  let browser;
  const apiPaths = [];
  const pageErrors = [];

  const writeEvent = (response, event) => {
    response.write(`id: ${event.event_id}\nevent: update\ndata: ${JSON.stringify(event)}\n\n`);
  };
  const publish = event => {
    if (event.summary) latestUnread = event.summary.unread_count;
    eventLog.push(event);
    for (const response of streams) writeEvent(response, event);
  };

  apiServer = createServer((request, response) => {
    const path = new URL(request.url, "http://localhost").pathname;
    apiPaths.push(path);
    if (path === "/api/panel/events") {
      const lastEventId = Number(request.headers["last-event-id"] || 0);
      lastEventIds.push(lastEventId);
      response.writeHead(200, {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        Connection: "keep-alive",
      });
      response.write("retry: 250\n\n");
      streams.add(response);
      maxActiveStreams = Math.max(maxActiveStreams, streams.size);
      response.on("close", () => streams.delete(response));
      for (const event of eventLog) {
        if (event.event_id > lastEventId) writeEvent(response, event);
      }
      return;
    }

    let body = {};
    if (path === "/api/panel/me") {
      body = { role: "admin", full_name: "Администратор" };
    } else if (path === "/api/panel/conversations") {
      inboxRequests += 1;
      body = [];
    } else if (path === "/api/panel/personal-conversations") {
      personalRequests += 1;
      pendingPersonalResponses.push(response);
      return;
    } else if (path === "/api/admin/users") {
      body = [];
    } else if (path === "/api/admin/overview") {
      body = { teachers: [] };
    } else if (path === "/api/admin/boards/objects") {
      body = [];
    } else if (path === "/api/panel/personal-conversations/5/messages") {
      body = [{
        id: 77,
        sender: "Администратор",
        sender_role: "admin",
        can_delete: false,
        content_type: "text",
        text: "Проверка адресной синхронизации",
        metadata: {},
        delivery_status: "delivered",
        panel_read_at: null,
        created_at: "2026-11-21T10:00:00+00:00",
      }];
    } else if (path === "/api/panel/personal-conversations/5/sync") {
      syncRequests += 1;
      body = {
        messages: syncNewMessages,
        updated_messages: [{
          id: 77,
          delivery_status: "delivered",
          panel_read_at: "2026-11-21T11:00:00+00:00",
        }],
        summary: { ...personalChat, unread_count: latestUnread },
      };
    }

    response.writeHead(200, { "Content-Type": "application/json" });
    response.end(JSON.stringify(body));
  });

  try {
    await new Promise(resolve => apiServer.listen(API_PORT, "127.0.0.1", resolve));
    vite = spawn(process.execPath, [
      "node_modules/vite/bin/vite.js",
      "--host", "127.0.0.1",
      "--port", String(APP_PORT),
      "--strictPort",
    ], { cwd: process.cwd(), env: { ...process.env, VITE_API_BASE_URL: "" }, stdio: "ignore" });
    await waitFor(async () => {
      const response = await fetch(APP_URL);
      return response.ok;
    });

    browser = await chromium.launch({ headless: true });
    // Логотип входа центрирован над UknowApp, не соприкасается с
    // переключателем темы и не выходит за экран на узких телефонах.
    const loginContext = await browser.newContext();
    try {
      const loginPage = await loginContext.newPage();
      await loginPage.goto(APP_URL);
      await loginPage.locator(".login-card .login-logo").waitFor({ state: "visible" });
      for (const width of [320, 390, 768, 1280]) {
        await loginPage.setViewportSize({ width, height: 800 });
        for (const theme of ["light", "dark-soft"]) {
          const layout = await loginPage.evaluate(nextTheme => {
            document.documentElement.dataset.theme = nextTheme;
            const rect = selector => {
              const box = document.querySelector(selector).getBoundingClientRect();
              return { x: box.x, y: box.y, right: box.right, bottom: box.bottom, width: box.width };
            };
            return {
              card: rect(".login-card"),
              brand: rect(".login-brand"),
              logo: rect(".login-logo"),
              heading: rect(".login-brand h1"),
              theme: rect(".login-theme-toggle"),
              loaded: document.querySelector(".login-logo").naturalWidth > 0,
            };
          }, theme);
          assert.ok(layout.loaded, "login logo asset loads");
          assert.ok(layout.logo.width >= 100, `${width}px: large login logo`);
          assert.ok(Math.abs(layout.logo.x + layout.logo.width / 2 - layout.card.x - layout.card.width / 2) <= 1,
            `${width}px ${theme}: logo centered in login panel`);
          assert.ok(Math.abs(layout.heading.x + layout.heading.width / 2 - layout.card.x - layout.card.width / 2) <= 1,
            `${width}px ${theme}: UknowApp heading centered`);
          assert.ok(layout.logo.bottom < layout.heading.y,
            `${width}px ${theme}: logo above heading`);
          assert.ok(layout.logo.right < layout.theme.x || layout.logo.bottom < layout.theme.y,
            `${width}px ${theme}: logo does not overlap theme control`);
          assert.ok(layout.card.x >= -1 && layout.card.right <= width + 1,
            `${width}px ${theme}: login panel fits viewport`);
        }
      }
    } finally {
      await loginContext.close();
    }
    // Личный кабинет учителя: ровно две вкладки, собственные ученики
    // в «Структуре», возврат к существующему списку диалогов.
    const teacherContext = await browser.newContext();
    try {
      await teacherContext.addInitScript(() => localStorage.setItem("uknowapp-auth", "1"));
      const teacherPage = await teacherContext.newPage();
      await teacherPage.route("**/api/panel/me", route => route.fulfill({
        status: 200, contentType: "application/json",
        body: JSON.stringify({ role: "teacher", user_id: 7, full_name: "Светлана Ивановна" }),
      }));
      await teacherPage.route("**/api/panel/conversations", route => route.fulfill({
        status: 200, contentType: "application/json",
        body: JSON.stringify([{
          id: 15,
          type: "assignment",
          student: { id: 27, full_name: "Тестовый ученик" },
          teacher: { id: 7, full_name: "Светлана Ивановна" },
          unread_count: 0,
          created_at: "2026-11-23T10:00:00+00:00",
        }]),
      }));
      const pendingTeacherPersonalInbox = [];
      await teacherPage.route("**/api/panel/personal-conversations", route => {
        pendingTeacherPersonalInbox.push(route);
      });
      await teacherPage.goto(APP_URL + "/structure");
      await teacherPage.getByRole("button", { name: "Структура", exact: true })
        .waitFor({ state: "visible" });
      assert.equal(await teacherPage.getByRole("button", { name: "Диалоги", exact: true }).count(), 1);
      await teacherPage.getByText("Мои ученики").waitFor({ state: "visible" });
      await teacherPage.getByText("Тестовый ученик").waitFor({ state: "visible" });
      assert.equal(pendingTeacherPersonalInbox.length, 1,
        "teacher's assigned students render before the slower personal-inbox response");
      await pendingTeacherPersonalInbox.shift().fulfill({
        status: 200, contentType: "application/json", body: "[]",
      });
      assert.equal(await teacherPage.getByRole("button", { name: "Добавить участника" }).count(), 0);
      await teacherPage.getByRole("button", { name: "Диалоги", exact: true }).click();
      await teacherPage.locator(".chat-list").waitFor({ state: "visible" });
      await teacherPage.getByRole("button", { name: "Структура", exact: true }).click();
      await teacherPage.getByText("Тестовый ученик").waitFor({ state: "visible" });
    } finally {
      await teacherContext.close();
    }
    const context = await browser.newContext();
    await context.addInitScript(() => localStorage.setItem("uknowapp-auth", "1"));
    const page = await context.newPage();
    page.on("pageerror", error => pageErrors.push(error.stack || error.message));
    await page.goto(APP_URL + "/boards");
    try {
      await page.getByRole("button", { name: "Доски" }).waitFor({ state: "visible" });
    } catch (error) {
      console.log("Browser page after startup:", await page.locator("body").innerText());
      console.log("API requests:", apiPaths);
      console.log("Browser errors:", pageErrors);
      throw error;
    }

    // Opening a dialog must retain the editor state owned by the active route.
    await page.getByRole("button", { name: "Структура", exact: true }).click();
    await page.getByRole("button", { name: "Добавить участника" }).click();
    const participant = page.getByRole("dialog", { name: "Добавить участника" });
    assert.equal(await participant.getByRole("combobox", { name: "Роль", exact: true }).inputValue(), "student");
    await participant.getByLabel("Имя и фамилия").fill("Учебный профиль");
    await participant.getByRole("combobox", { name: "Роль", exact: true }).selectOption("teacher");
    assert.equal(await participant.getByLabel("Имя и фамилия").inputValue(), "Учебный профиль");
    assert.equal(await participant.getByLabel("Доп. инфо").count(), 0);
    await page.keyboard.press("Escape");
    await participant.waitFor({ state: "detached" });
    await page.getByRole("button", { name: "Доски", exact: true }).click();

    // Проверяем оформление ролей в обеих темах после CSS-рефакторинга.
    const themeStyles = await page.evaluate(() => {
      const oldTheme = document.documentElement.dataset.theme;
      const wrapper = document.createElement("div");
      wrapper.className = "workspace-content";
      wrapper.innerHTML = [
        '<div class="admin-card"></div>',
        '<div class="teacher-card"></div>',
        '<div class="student-card"></div>',
      ].join("");
      document.body.append(wrapper);
      const result = {};
      for (const theme of ["light", "dark-soft"]) {
        document.documentElement.dataset.theme = theme;
        result[theme] = {
          root: getComputedStyle(document.documentElement).backgroundColor,
          teacher: getComputedStyle(wrapper.querySelector(".teacher-card")).background,
          student: getComputedStyle(wrapper.querySelector(".student-card")).background,
        };
      }
      wrapper.remove();
      document.documentElement.dataset.theme = oldTheme;
      return result;
    });
    assert.equal(themeStyles["dark-soft"].root, "rgb(32, 41, 56)");
    assert.notEqual(themeStyles.light.teacher, themeStyles["dark-soft"].teacher);
    assert.notEqual(themeStyles.light.student, themeStyles["dark-soft"].student);

    // Все вкладки используют один скролл-контейнер и одно оформление фона.
    // Не заменяем узлы приложения: добавляем и затем удаляем только тестовый элемент.
    for (const width of [390, 1280]) {
      await page.setViewportSize({ width, height: 800 });
      for (const theme of ["light", "dark-soft"]) {
        const isolation = await page.evaluate(currentTheme => {
          const root = document.documentElement;
          const previousTheme = root.dataset.theme;
          root.dataset.theme = currentTheme;
          const shell = document.querySelector(".workspace-shell");
          const sidebar = shell.querySelector(".sidebar");
          const content = shell.querySelector(".workspace-content");
          const nativeScroll = window.matchMedia("(max-width: 1024px) and (display-mode: browser)").matches;
          if (nativeScroll) window.scrollTo(0, 0);
          const initialTop = sidebar.getBoundingClientRect().top;
          const previousScroll = content.scrollTop;
          const tallSection = document.createElement("div");
          tallSection.style.cssText = "height:2200px;min-height:2200px;flex-shrink:0;";
          try {
            content.append(tallSection);
            if (nativeScroll) window.scrollTo(0, 500);
            else content.scrollTop = 500;
            const bg = getComputedStyle(root).getPropertyValue("--workspace-background").trim();
            const canvas = document.createElement("div");
            canvas.style.backgroundColor = bg;
            document.body.append(canvas);
            const resolvedBackground = getComputedStyle(canvas).backgroundColor;
            canvas.remove();
            return {
              scrollTop: nativeScroll ? window.scrollY : content.scrollTop,
              shellPosition: getComputedStyle(shell).position,
              sidebarPosition: getComputedStyle(sidebar).position,
              sidebarTop: sidebar.getBoundingClientRect().top,
              initialTop,
              windowScroll: window.scrollY,
              docOverflow: getComputedStyle(root).overflow,
              bodyOverflow: getComputedStyle(document.body).overflow,
              rootOverflow: getComputedStyle(document.getElementById("root")).overflow,
              sidebarOverscroll: getComputedStyle(sidebar).overscrollBehaviorY,
              sidebarTouchAction: getComputedStyle(sidebar).touchAction,
              rootBackground: getComputedStyle(root).backgroundColor,
              sidebarBackground: getComputedStyle(sidebar).backgroundColor,
              bodyBackground: getComputedStyle(document.body).backgroundColor,
              shellBackground: getComputedStyle(shell).backgroundColor,
              mainBackground: getComputedStyle(shell.querySelector(".content, .main")).backgroundColor,
              expectedBackground: resolvedBackground,
            };
          } finally {
            tallSection.remove();
            content.scrollTop = previousScroll;
            if (nativeScroll) window.scrollTo(0, 0);
            root.dataset.theme = previousTheme;
          }
        }, theme);
        assert.equal(isolation.shellPosition, width < 1025 ? "relative" : "fixed",
          `${width}px ${theme}: Safari browser uses document-flow, desktop uses fixed shell`);
        if (width < 1025) {
          assert.equal(isolation.sidebarPosition, "sticky",
            `${width}px ${theme}: sidebar is sticky above the document`);
        }
        assert.ok(isolation.scrollTop >= 400, `${width}px ${theme}: content can scroll`);
        assert.equal(isolation.sidebarTop, isolation.initialTop, `${width}px ${theme}: sidebar stays in place`);
        assert.equal(isolation.windowScroll >= 400, width < 1025,
          `${width}px ${theme}: only mobile Safari scrolls the document`);
        for (const [label, value] of [
          ["html", isolation.docOverflow], ["body", isolation.bodyOverflow],
          ["root", isolation.rootOverflow],
        ]) {
          assert.equal(value, width < 1025 ? "clip visible" : "hidden",
            `${width}px ${theme}: ${label} uses correct scroll strategy`);
        }
        assert.equal(isolation.sidebarOverscroll, "none", `${width}px ${theme}: sidebar overscroll`);
        if (width < 1025) assert.equal(isolation.sidebarTouchAction, "pan-x", "mobile nav permits only horizontal swipes");
        // Mobile, Desktop и PWA используют один фон html без внутренних подложек.
        assert.equal(isolation.rootBackground, isolation.expectedBackground,
          `${width}px ${theme}: one themed background for every viewport`);
        assert.equal(isolation.sidebarBackground,
          width < 1025 ? isolation.expectedBackground : "rgba(0, 0, 0, 0)",
          `${width}px ${theme}: mobile overlay matches the shared theme surface`);
        for (const layer of ["bodyBackground", "shellBackground", "mainBackground"]) {
          assert.equal(isolation[layer], "rgba(0, 0, 0, 0)",
            `${width}px ${theme}: transparent ${layer}, no extra underlay`);
        }
      }
    }
    await page.setViewportSize({ width: 1280, height: 720 });

    // Меню, нижние пункты и действие создания используют единый шрифт и оформление.
    for (const width of [390, 1280]) {
      await page.setViewportSize({ width, height: 800 });
      for (const theme of ["light", "dark-soft"]) {
        const result = await page.evaluate(currentTheme => {
          const previous = document.documentElement.dataset.theme;
          document.documentElement.dataset.theme = currentTheme;
          const fixture = document.createElement("div");
          fixture.className = "workspace-shell";
          fixture.style.cssText = "position:fixed;left:0;top:0;visibility:hidden;pointer-events:none";
          fixture.innerHTML = `
            <aside class="sidebar">
              <div class="school-label">Управление школой</div>
              <nav>
                <button class="ui-menu-control" type="button">Диалоги</button>
                <button class="ui-menu-control" aria-current="page" type="button">Структура</button>
              </nav>
              <div class="sidebar-bottom">
                <button class="desktop-admin-extra ui-menu-control" type="button">Дополнительно</button>
                <button class="desktop-sidebar-logout ui-menu-control" type="button">Выход</button>
              </div>
            </aside>
            <div class="workspace-content">
              <div class="admin-card">Администратор</div>
              <button class="btn graph-add-participant ui-menu-control" type="button">Добавить участника</button>
              <div class="teacher-card"><div class="person-info"><b>Александра Епифанова</b></div></div>
            </div>
          `;
          document.body.append(fixture);
          const styleOf = selector => {
            const style = getComputedStyle(fixture.querySelector(selector));
            return {
              family: style.fontFamily,
              size: style.fontSize,
              weight: style.fontWeight,
              background: style.backgroundColor,
              border: style.borderTopColor,
              borderWidth: style.borderTopWidth,
              radius: style.borderTopLeftRadius,
              display: style.display,
            };
          };
          const result = {
            schoolLabel: styleOf(".sidebar .school-label"),
            nav: styleOf(".sidebar nav button:not([aria-current])"),
            additional: styleOf(".desktop-admin-extra"),
            logout: styleOf(".desktop-sidebar-logout"),
            create: styleOf(".graph-add-participant"),
            selected: styleOf(".sidebar nav button[aria-current=\"page\"]"),
            teacher: styleOf(".teacher-card .person-info b"),
          };
          fixture.remove();
          document.documentElement.dataset.theme = previous;
          return result;
        }, theme);
        assert.equal(result.schoolLabel.display === "none", width < 1025,
          `${theme} ${width}px: подпись школы видна только на компьютере`);
        const expected = result.nav;
        for (const name of ["additional", "logout", "create"]) {
          const item = result[name];
          assert.equal(item.family, expected.family, `${theme} ${width}px ${name}: шрифт`);
          assert.equal(item.background, expected.background, `${theme} ${width}px ${name}: фон`);
          assert.equal(item.border, expected.border, `${theme} ${width}px ${name}: рамка`);
          assert.equal(item.borderWidth, "1px", `${theme} ${width}px ${name}: толщина рамки`);
          assert.equal(item.radius, expected.radius, `${theme} ${width}px ${name}: скругление`);
          if (width === 1280 || name === "create") {
            assert.equal(item.size, expected.size, `${theme} ${width}px ${name}: размер текста`);
          }
        }
        assert.equal(result.teacher.family, expected.family, `${theme}: гарнитура карточки`);
        assert.notEqual(result.selected.background, expected.background, `${theme}: выделение активного раздела`);
        for (const name of ["additional", "logout"]) {
          assert.equal(result[name].display === "none", width < 1025,
            `${theme} ${width}px ${name}: правильная видимость пункта`);
        }
      }
    }
    await page.setViewportSize({ width: 1280, height: 720 });

    // Плавно пересекаем desktop/tablet/mobile breakpoints без перерисовки
    // приложения и без принудительных CSS-инвалидаций на каждом пикселе.
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.evaluate(() => new Promise(resolve =>
      requestAnimationFrame(() => requestAnimationFrame(resolve))));
    await page.evaluate(() => {
      const root = document.documentElement;
      const shell = document.querySelector(".workspace-shell");
      window.__resizeShell = shell;
      window.__resizeWrites = { viewport: 0, sidebar: 0 };
      const viewportObserver = new MutationObserver(records => {
        window.__resizeWrites.viewport += records.length;
      });
      const sidebarObserver = new MutationObserver(records => {
        window.__resizeWrites.sidebar += records.length;
      });
      viewportObserver.observe(root, { attributes: true, attributeFilter: ["style"] });
      sidebarObserver.observe(shell, { attributes: true, attributeFilter: ["style"] });
      window.__stopResizeTracking = () => {
        window.__resizeWrites.viewport += viewportObserver.takeRecords().length;
        window.__resizeWrites.sidebar += sidebarObserver.takeRecords().length;
        viewportObserver.disconnect();
        sidebarObserver.disconnect();
        const result = {
          ...window.__resizeWrites,
          preservedShell: window.__resizeShell === document.querySelector(".workspace-shell"),
        };
        delete window.__resizeShell;
        delete window.__resizeWrites;
        delete window.__stopResizeTracking;
        return result;
      };
    });
    for (const width of [1025, 1024, 900, 761, 760, 600, 390, 320, 760, 1024, 1025, 1280, 1600]) {
      await page.setViewportSize({ width, height: 800 });
      const state = await page.evaluate(() => new Promise(resolve =>
        requestAnimationFrame(() => requestAnimationFrame(() => {
          const shell = document.querySelector(".workspace-shell");
          const sidebar = shell.querySelector(".sidebar");
          const mobile = matchMedia("(max-width: 1024px)").matches;
          resolve({
            screenWidth: window.innerWidth,
            documentWidth: document.documentElement.scrollWidth,
            position: getComputedStyle(shell).position,
            mobile,
            sidebarHeight: Math.ceil(sidebar.getBoundingClientRect().height),
            measuredHeight: parseFloat(shell.style.getPropertyValue("--workspace-sidebar-height")),
          });
        }))));
      assert.equal(state.screenWidth, width);
      assert.ok(state.documentWidth <= width + 1, `${width}px: no horizontal page overflow`);
      assert.equal(state.position, state.mobile ? "relative" : "fixed",
        `${width}px: workspace switches scroll strategy without remounting`);
      if (state.mobile) {
        assert.ok(Math.abs(state.sidebarHeight - state.measuredHeight) <= 1,
          `${width}px: mobile content padding tracks real navigation height`);
      }
    }
    const resizeWrites = await page.evaluate(() => window.__stopResizeTracking());
    assert.equal(resizeWrites.preservedShell, true, "resizing preserves the live workspace DOM");
    assert.ok(resizeWrites.viewport <= 2,
      `width-only resizing must not rewrite root viewport CSS on every event: ${resizeWrites.viewport}`);
    assert.ok(resizeWrites.sidebar < 13,
      `mobile sidebar should update only for actual height changes: ${resizeWrites.sidebar}`);
    await page.setViewportSize({ width: 1280, height: 720 });

    // Контур вокруг workspace не должен появляться после закрытия формы
    // и при переводе фокуса на прокручиваемую область. У кнопок один фокусный
    // контур без второй box-shadow-рамки; клавиатурный фокус остаётся видимым.
    for (const width of [390, 1024, 1280]) {
      await page.setViewportSize({ width, height: 800 });
      for (const theme of ["light", "dark-soft"]) {
        await page.keyboard.press("Tab");
        const focus = await page.evaluate(nextTheme => {
          const root = document.documentElement;
          const priorTheme = root.dataset.theme;
          const priorFocused = document.activeElement;
          root.dataset.theme = nextTheme;
          const fixture = document.createElement("div");
          fixture.className = "workspace-shell";
          fixture.style.cssText = "position:fixed;top:0;left:0;width:650px;height:600px;opacity:0;pointer-events:none;z-index:-1";
          fixture.innerHTML = `
            <aside class="sidebar">
              <nav><button class="ui-menu-control" aria-current="page">Диалоги</button></nav>
            </aside>
            <main class="content">
              <div class="workspace-content" tabindex="0">
                <div class="search workspace-search"><input aria-label="Поиск"></div>
                <section class="chat-list">
                  <div class="chat-section-tabs">
                    <button class="chat-section-tab ui-toolbar-tab" aria-pressed="true">Участники</button>
                  </div>
                  <div class="chat-items">
                    <button class="chat-item student-card selected" aria-pressed="true">Диалог</button>
                  </div>
                </section>
                <div class="teacher-card">
                  <div class="person-actions">
                    <button class="icon-btn ui-icon-button" aria-label="Редактировать">✎</button>
                  </div>
                </div>
                <button class="btn">Добавить участника</button>
              </div>
            </main>
          `;
          document.body.append(fixture);
          const inspect = selector => {
            const node = fixture.querySelector(selector);
            node.focus({ preventScroll: true });
            const css = getComputedStyle(node);
            return {
              visibleFocus: node.matches(":focus-visible"),
              outline: css.outlineStyle,
              outlineWidth: css.outlineWidth,
              shadow: css.boxShadow,
              transition: css.transitionProperty,
            };
          };
          try {
            const main = inspect(".workspace-content");
            const menu = inspect(".ui-menu-control");
            const tab = inspect(".chat-section-tab");
            const chat = inspect(".chat-item");
            const icon = inspect(".ui-icon-button");
            const button = inspect(".workspace-content > .btn");
            const input = inspect(".search input");
            const searchShadow = getComputedStyle(fixture.querySelector(".search")).boxShadow;
            return { main, menu, tab, chat, icon, button, input, searchShadow };
          } finally {
            fixture.remove();
            if (priorFocused?.isConnected && typeof priorFocused.focus === "function") {
              priorFocused.focus({ preventScroll: true });
            }
            root.dataset.theme = priorTheme;
          }
        }, theme);
        assert.equal(focus.main.visibleFocus, true,
          `${width}px ${theme}: scroll region is keyboard-focusable`);
        assert.equal(focus.main.outline, "none",
          `${width}px ${theme}: no full-screen white/lavender border`);
        assert.equal(focus.main.shadow, "none",
          `${width}px ${theme}: no purple vertical stripe when workspace receives focus`);
        for (const name of ["menu", "tab", "chat", "icon", "button"]) {
          assert.equal(focus[name].visibleFocus, true,
            `${width}px ${theme}: ${name} remains keyboard accessible`);
          assert.equal(focus[name].outline, "solid",
            `${width}px ${theme}: ${name} has a single visible focus ring`);
          assert.equal(focus[name].outlineWidth, "2px");
          if (name === "chat") {
            assert.match(focus[name].shadow, /inset/,
              `${width}px ${theme}: selected chat keeps its left indicator`);
            assert.equal((focus[name].shadow.match(/rgba?\(/g) || []).length, 1,
              `${width}px ${theme}: selected chat has no second outer glow`);
          } else {
            assert.equal(focus[name].shadow, "none",
              `${width}px ${theme}: ${name} has no second glow border`);
          }
          if (name === "icon" || name === "button") {
            assert.ok(!/(^|,)\s*(transform|box-shadow)/.test(focus[name].transition),
              `${width}px ${theme}: no hover displacement or shadow animation for ${name}`);
          }
        }
        assert.equal(focus.input.shadow, "none",
          `${width}px ${theme}: input and search wrapper do not draw two focus glows`);
        assert.notEqual(focus.searchShadow, "none",
          `${width}px ${theme}: search still shows a visible keyboard focus state`);
      }
    }
    await page.setViewportSize({ width: 1280, height: 720 });

    // Указатель не должен сдвигать интерактивные элементы, провоцируя
    // повторный mouseenter/mouseleave и визуальное мерцание рамок.
    for (const width of [390, 1280]) {
      await page.setViewportSize({ width, height: 800 });
      for (const theme of ["light", "dark-soft"]) {
        await page.evaluate(currentTheme => {
          document.documentElement.dataset.theme = currentTheme;
          const fixture = document.createElement("div");
          fixture.id = "hover-stability-fixture";
          fixture.className = "workspace-content";
          fixture.style.cssText = "position:fixed;top:80px;left:20px;width:300px;height:300px;z-index:99999;padding:14px;background:var(--surface);pointer-events:auto";
          fixture.innerHTML = `
            <button class="btn" type="button">Добавить</button>
            <section class="teacher-branch">
              <div class="teacher-card">Преподаватель</div>
            </section>
            <div class="student-card">Ученик</div>
          `;
          document.body.append(fixture);
        }, theme);
        try {
          for (const selector of [".btn", ".teacher-card", ".student-card"]) {
            const target = page.locator("#hover-stability-fixture " + selector);
            await page.mouse.move(5, 5);
            const original = await target.boundingBox();
            await target.hover();
            const hovered = await target.boundingBox();
            const style = await target.evaluate(el => {
              const css = getComputedStyle(el);
              return { transform: css.transform, outline: css.outlineStyle };
            });
            for (const dimension of ["x", "y", "width", "height"]) {
              assert.ok(Math.abs(original[dimension] - hovered[dimension]) < 0.5,
                `${width}px ${theme} ${selector}: hover must not shift ${dimension}`);
            }
            assert.equal(style.transform, "none",
              `${width}px ${theme} ${selector}: no animated hover transform`);
            assert.equal(style.outline, "none",
              `${width}px ${theme} ${selector}: pointer hover must not create a focus ring`);
          }
        } finally {
          await page.evaluate(() => document.getElementById("hover-stability-fixture")?.remove());
        }
      }
    }
    await page.setViewportSize({ width: 1280, height: 720 });

    // В карточках структуры длинные имена не переносят кнопки действий
    // на вторую строку. Проверяем каждую контрольную ширину и обе темы.
    for (const width of [320, 340, 375, 390, 430, 480, 600, 760, 761, 900, 1024, 1025, 1280, 1440, 1600]) {
      await page.setViewportSize({ width, height: 800 });
      for (const theme of ["light", "dark-soft"]) {
        const layout = await page.evaluate(currentTheme => {
          const root = document.documentElement;
          const previousTheme = root.dataset.theme;
          root.dataset.theme = currentTheme;
          const host = document.createElement("div");
          host.className = "workspace-content";
          host.style.cssText = "position:absolute;top:0;left:0;width:calc(100vw - 20px);height:auto;visibility:hidden;pointer-events:none";
          host.innerHTML = `
            <div class="structure-scroll">
              <div class="admin-card">Администратор</div>
              <div class="grid">
                <section class="teacher-branch">
                  <div class="teacher-card">
                    <div class="person-main"><div class="avatar teacher-avatar"></div>
                      <div class="person-info"><b>Александра Епифанова Очень Длинная Фамилия</b><small>Учитель · 1 учен.</small></div>
                    </div>
                    <div class="person-actions">
                      <button class="ui-icon-button teacher-collapse-btn">▼</button>
                      <button class="ui-icon-button">✎</button>
                    </div>
                  </div>
                  <div class="student-list">
                    <div class="student-card">
                      <div class="person-main"><div class="avatar student-avatar"></div>
                        <div class="person-info"><b>Наталья Воронова Очень-Очень Длинная Фамилия</b><small>вт 20:00 / чт 14:00</small></div>
                      </div>
                      <button class="ui-icon-button graph-person-action">✎</button>
                      <button class="ui-icon-button graph-person-action">↗</button>
                    </div>
                  </div>
                </section>
              </div>
              <section class="unassigned">
                <h2 class="unassigned-title">Ученики без учителя</h2>
                <div class="unassigned-grid">
                  <div class="student-card unassigned-student-card">
                    <div class="person-main"><div class="avatar student-avatar"></div>
                      <div class="person-info"><b>agggfasg sfgsf Наталья Воронова Очень Длинное Имя</b><small>вт 20:00 / чт 14:00</small></div>
                    </div>
                    <div class="unassigned-student-actions">
                      <button class="ui-icon-button graph-person-action">✎</button>
                      <button class="btn outline">Назначить</button>
                    </div>
                  </div>
                  <div class="student-card unassigned-student-card">
                    <div class="person-main"><div class="avatar student-avatar"></div>
                      <div class="person-info"><b>123123123</b></div>
                    </div>
                    <div class="unassigned-student-actions">
                      <button class="ui-icon-button graph-person-action">✎</button>
                      <button class="btn outline">Назначить</button>
                    </div>
                  </div>
                </div>
              </section>
            </div>
          `;
          document.body.append(host);
          const rect = element => {
            const box = element.getBoundingClientRect();
            return { x: box.x, y: box.y, right: box.right, bottom: box.bottom, width: box.width, height: box.height };
          };
          const result = [];
          try {
            for (const [selector, actionsSelector] of [
              [".teacher-card", ".person-actions > button"],
              [".student-list > .student-card", ":scope > .graph-person-action"],
              [".unassigned-grid > .unassigned-student-card:first-child", ".unassigned-student-actions > button"],
              [".unassigned-grid > .unassigned-student-card:last-child", ".unassigned-student-actions > button"],
            ]) {
              const card = host.querySelector(selector);
              const main = card.querySelector(":scope > .person-main");
              const title = main.querySelector(".person-info > b");
              const actionButtons = [...card.querySelectorAll(actionsSelector)];
              const css = getComputedStyle(title);
              result.push({
                card: rect(card), main: rect(main), name: rect(title),
                actions: actionButtons.map(rect),
                fontSize: parseFloat(css.fontSize),
                whiteSpace: css.whiteSpace,
                overflow: css.overflow,
                containerType: getComputedStyle(title.parentElement).containerType,
              });
            }
            return result;
          } finally {
            host.remove();
            root.dataset.theme = previousTheme;
          }
        }, theme);
        assert.equal(layout.length, 4);
        for (const [index, card] of layout.entries()) {
          assert.equal(card.actions.length, 2,
            `${width}px ${theme} card ${index}: both action buttons remain visible`);
          const [first, second] = card.actions;
          assert.ok(first.right <= second.x + 0.5,
            `${width}px ${theme} card ${index}: action buttons never stack or overlap`);
          assert.ok(Math.abs((first.y + first.bottom) - (second.y + second.bottom)) < 2,
            `${width}px ${theme} card ${index}: action buttons stay on the same line`);
          assert.ok(first.y >= card.card.y - 1 && second.bottom <= card.card.bottom + 1,
            `${width}px ${theme} card ${index}: buttons never escape the card`);
          assert.ok(second.right <= card.card.right + 1,
            `${width}px ${theme} card ${index}: buttons never overflow the right edge`);
          assert.ok(card.main.right <= first.x + 1,
            `${width}px ${theme} card ${index}: long name never overlaps action buttons`);
          assert.equal(card.whiteSpace, "nowrap");
          assert.equal(card.overflow, "hidden");
          assert.equal(card.containerType, "inline-size");
          assert.ok(card.fontSize >= 9.9 && card.fontSize <= 13.1,
            `${width}px ${theme} card ${index}: name fits within 10–13px typography range`);
          assert.ok(card.name.right <= card.main.right + 1);
        }
      }
    }
    await page.setViewportSize({ width: 1280, height: 720 });

    // Структура: построчный Grid сохраняет колонки при раскрытии учеников.
    // Запрещаем прежнюю автоматическую перебалансировку CSS columns.
    for (const width of [390, 760, 1024, 1280, 1385, 1600]) {
      await page.setViewportSize({ width, height: 800 });
      const layout = await page.evaluate(() => {
        const host = document.createElement("div");
        host.className = "workspace-content";
        host.style.cssText = "position:absolute;top:0;left:0;width:calc(100vw - 20px);height:auto;visibility:hidden;pointer-events:none";
        host.innerHTML = `
          <div class="graph-legend-row">
            <div class="legend graph-legend">Учителя 6</div>
            <button class="graph-add-participant ui-menu-control">Добавить участника</button>
          </div>
          <div class="structure-scroll">
            <div class="admin-card"><img src="/logo-main.svg" alt=""><div><b>Администратор</b></div></div>
            <div class="grid">
              ${[3, 0, 2, 1, 4, 0].map((count, index) => `
                <section class="teacher-branch" data-index="${index}">
                  <div class="teacher-card">Учитель ${index + 1}</div>
                  <button class="add-student">Назначить ученика</button>
                  <div class="student-list">
                    ${count ? Array.from({ length: count }, (_, i) =>
                      `<div class="student-card">Ученик ${i + 1}</div>`).join("")
                      : '<div class="empty-students">Нет назначенных учеников</div>'}
                  </div>
                </section>
              `).join("")}
            </div>
          </div>
        `;
        document.body.append(host);
        try {
          const rect = selector => host.querySelector(selector).getBoundingClientRect();
          const grid = host.querySelector(".grid");
          const styles = getComputedStyle(grid);
          const measure = () => [...grid.children].map(node => {
            const box = node.getBoundingClientRect();
            return { left: Math.round(box.left), top: box.top, bottom: box.bottom, right: box.right };
          });
          const before = measure();
          const first = grid.children[0];
          for (const child of first.querySelectorAll(".add-student, .student-list")) {
            child.style.display = "none";
          }
          first.classList.add("is-collapsed");
          const collapsed = measure();
          for (const child of first.querySelectorAll(".add-student, .student-list")) {
            child.style.removeProperty("display");
          }
          first.classList.remove("is-collapsed");
          const reopened = measure();
          return {
            display: styles.display,
            flow: styles.gridAutoFlow,
            columnCount: styles.columnCount,
            gridWidth: grid.getBoundingClientRect().width,
            before, collapsed, reopened,
            gapBeforeAdmin: rect(".admin-card").top - rect(".graph-legend-row").bottom,
            gapAfterAdmin: rect(".grid").top - rect(".admin-card").bottom,
          };
        } finally {
          host.remove();
        }
      });
      const expectedCols = Math.max(1, Math.floor((layout.gridWidth + 12) / 332));
      const checkRows = (cards, stage) => {
        assert.equal(cards.length, 6);
        for (let row = 0; row < Math.ceil(cards.length / expectedCols); row++) {
          const group = cards.slice(row * expectedCols, (row + 1) * expectedCols);
          assert.ok(group.every(card => Math.abs(card.top - group[0].top) <= 1),
            `${width}px ${stage}: cards must align by rows`);
          assert.ok(group.every((card, i) => i === 0 || card.left > group[i - 1].left),
            `${width}px ${stage}: teacher order must follow the DOM`);
          if (row > 0) {
            const previous = cards.slice((row - 1) * expectedCols, row * expectedCols);
            const gap = group[0].top - Math.max(...previous.map(card => card.bottom));
            assert.ok(gap >= 10 && gap <= 14,
              `${width}px ${stage}: consistent 12px row spacing, got ${gap}`);
          }
        }
      };
      assert.equal(layout.display, "grid", `${width}px: use Grid, not CSS columns`);
      assert.equal(layout.flow, "row", `${width}px: keep row-major order`);
      assert.equal(layout.columnCount, "auto", `${width}px: disable masonry rebalancing`);
      for (const stage of ["before", "collapsed", "reopened"]) {
        checkRows(layout[stage], stage);
        assert.ok(layout[stage].every(card => card.right <= width + 1),
          `${width}px ${stage}: cards stay within viewport`);
      }
      for (let i = 0; i < 6; i++) {
        assert.equal(layout.before[i].left, layout.collapsed[i].left,
          `${width}px: collapsing students must never move teacher ${i + 1} to another column`);
        assert.equal(layout.before[i].left, layout.reopened[i].left,
          `${width}px: reopening students must preserve teacher ${i + 1} column`);
        assert.ok(Math.abs(layout.before[i].top - layout.reopened[i].top) <= 1,
          `${width}px: reopening restores the original card positions`);
      }
      assert.ok(layout.collapsed[0].bottom < layout.before[0].bottom,
        `${width}px: collapsing students changes only content height`);
      assert.ok(layout.gapBeforeAdmin <= 30, `${width}px: compact toolbar-to-admin gap`);
      assert.ok(layout.gapAfterAdmin <= 11, `${width}px: compact admin-to-teachers gap`);
    }
    await page.setViewportSize({ width: 1280, height: 720 });

    // Эмуляция закрытого/открытого visualViewport на iOS Safari.
    // Клавиатура не должна перекрывать историю, поле сообщения или модальную форму.
    for (const width of [375, 390, 760, 1024]) {
      await page.setViewportSize({ width, height: 800 });
      for (const theme of ["light", "dark-soft"]) {
        const result = await page.evaluate(selectedTheme => {
          const root = document.documentElement;
          const oldTheme = root.dataset.theme;
          const oldKeyboard = root.getAttribute("data-workspace-keyboard");
          const oldHeight = root.style.getPropertyValue("--workspace-viewport-height");
          const oldTop = root.style.getPropertyValue("--workspace-viewport-top");
          root.dataset.theme = selectedTheme;
          root.setAttribute("data-workspace-keyboard", "open");
          root.style.setProperty("--workspace-viewport-height", "340px");
          root.style.setProperty("--workspace-viewport-top", "0px");
          const host = document.createElement("div");
          host.className = "workspace-shell";
          host.id = "keyboard-layout-fixture";
          host.style.zIndex = "100";
          host.innerHTML = `
            <aside class="sidebar"><nav>Навигация</nav></aside>
            <main class="content">
              <header class="topbar">Верхняя панель</header>
              <div class="workspace-content">
                <section class="chat-list workspace-panel">Список диалогов</section>
                <section class="chat-detail">
                  <header class="chat-head">
                    <button class="btn mobile-chat-back">Назад</button>
                    <div class="chat-head-person">Администратор</div>
                  </header>
                  <div class="messages"><div class="message">Сообщение</div></div>
                  <form class="chat-composer">
                    <textarea rows="1" placeholder="Сообщение…"></textarea>
                    <div class="composer-footer">
                      <div class="composer-tools">
                        <label class="attach-control ui-icon-button">
                          <span>+</span><input type="file" aria-label="Выбрать файл">
                        </label>
                      </div>
                      <button class="btn primary composer-send" aria-label="Отправить">
                        <svg width="16" height="16"></svg><span>Отправить</span>
                      </button>
                    </div>
                  </form>
                </section>
              </div>
            </main>
          `;
          document.body.append(host);
          const rect = selector => {
            const node = host.querySelector(selector);
            const box = node.getBoundingClientRect();
            return { top: box.top, bottom: box.bottom, height: box.height, width: box.width };
          };
          try {
            const layout = {
              shell: host.getBoundingClientRect().height,
              sidebar: getComputedStyle(host.querySelector(".sidebar")).display,
              topbar: getComputedStyle(host.querySelector(".topbar")).display,
              content: rect(".workspace-content"),
              detail: rect(".chat-detail"),
              head: rect(".chat-head"),
              history: rect(".messages"),
              composer: rect(".chat-composer"),
              editor: rect("textarea"),
              footer: rect(".composer-footer"),
              send: rect(".composer-send"),
              attach: rect(".attach-control"),
              sendLabel: getComputedStyle(host.querySelector(".composer-send span")).display,
            };
            return layout;
          } finally {
            host.remove();
            root.dataset.theme = oldTheme;
            if (oldKeyboard === null) root.removeAttribute("data-workspace-keyboard");
            else root.setAttribute("data-workspace-keyboard", oldKeyboard);
            if (oldHeight) root.style.setProperty("--workspace-viewport-height", oldHeight);
            else root.style.removeProperty("--workspace-viewport-height");
            if (oldTop) root.style.setProperty("--workspace-viewport-top", oldTop);
            else root.style.removeProperty("--workspace-viewport-top");
          }
        }, theme);
        assert.ok(Math.abs(result.shell - 340) <= 1,
          `${width}px ${theme}: workspace tracks visible viewport, not 100lvh`);
        assert.equal(result.sidebar, "none");
        assert.equal(result.topbar, "none");
        assert.ok(result.content.top >= -1 && result.content.bottom <= 341);
        assert.ok(result.head.bottom <= result.history.top + 1);
        assert.ok(result.history.bottom <= result.composer.top + 1,
          `${width}px ${theme}: messages never overlap editor`);
        assert.ok(result.composer.bottom <= 341,
          `${width}px ${theme}: editor stays above keyboard`);
        assert.ok(result.editor.height >= 63,
          `${width}px ${theme}: message editor has usable touch height`);
        assert.ok(result.attach.width >= 40 && result.attach.height >= 40);
        assert.ok(result.send.width <= 48,
          `${width}px ${theme}: send action is compact`);
        assert.equal(result.sendLabel, "none",
          `${width}px ${theme}: send text is hidden only in mobile presentation`);
      }
    }
    await page.setViewportSize({ width: 1280, height: 720 });

    // На любой высоте браузерной панели нижняя часть вкладки остаётся доступной.
    // Проверяем телефон с открытой/закрытой панелью, планшет и десктоп.
    for (const { width, height } of [
      { width: 390, height: 720 }, { width: 390, height: 430 },
      { width: 768, height: 650 }, { width: 1280, height: 800 },
    ]) {
      await page.setViewportSize({ width, height });
      await page.waitForFunction(() => {
        const vv = window.visualViewport;
        const shell = document.querySelector(".workspace-shell");
        if (!shell) return false;
        if (matchMedia("(max-width: 1024px) and (display-mode: browser)").matches) {
          return getComputedStyle(shell).position === "relative";
        }
        return !vv || Math.abs(shell.getBoundingClientRect().height - vv.height) <= 2;
      });
      const state = await page.evaluate(() => {
        const viewport = window.visualViewport;
        const shell = document.querySelector(".workspace-shell");
        const content = shell.querySelector(".workspace-content");
        const bottom = (viewport?.offsetTop || 0) + (viewport?.height || window.innerHeight);
        const nativeScroll = matchMedia("(max-width: 1024px) and (display-mode: browser)").matches;
        const tall = document.createElement("div");
        tall.style.height = "1600px";
        tall.style.flexShrink = "0";
        content.append(tall);
        try {
          if (nativeScroll) window.scrollTo(0, document.documentElement.scrollHeight);
          else content.scrollTop = content.scrollHeight;
          return {
            nativeScroll,
            visibleBottom: bottom,
            shellBottom: shell.getBoundingClientRect().bottom,
            contentBottom: content.getBoundingClientRect().bottom,
            finalItemBottom: tall.getBoundingClientRect().bottom,
            scrollTop: nativeScroll ? window.scrollY : content.scrollTop,
            shellHeight: shell.getBoundingClientRect().height,
            viewportHeight: viewport?.height || window.innerHeight,
          };
        } finally {
          tall.remove();
          content.scrollTop = 0;
          if (nativeScroll) window.scrollTo(0, 0);
        }
      });
      assert.ok(state.nativeScroll
        ? state.shellHeight >= state.viewportHeight
        : Math.abs(state.shellHeight - state.viewportHeight) <= 2,
        `${width}x${height}: mobile document expands; desktop shell follows viewport`);
      assert.ok(state.shellBottom <= state.visibleBottom + 2,
        `${width}x${height}: shell does not hide behind browser toolbar`);
      assert.ok(state.contentBottom <= state.visibleBottom + 2,
        `${width}x${height}: section bottom stays visible`);
      assert.ok(state.scrollTop > 100, `${width}x${height}: content can scroll`);
      assert.ok(state.finalItemBottom <= state.visibleBottom + 2,
        `${width}x${height}: the last item remains reachable`);
    }

    // На iPhone обычный document рисуется ПОД Safari Liquid Glass.
    // Sidebar занимает собственную sticky-строку и не перемещается при скролле.
    await page.setViewportSize({ width: 390, height: 720 });
    await page.waitForFunction(() => {
      const shell = document.querySelector(".workspace-shell");
      return !!shell && getComputedStyle(shell).position === "relative";
    });
    for (const theme of ["light", "dark-soft"]) {
      const safeArea = await page.evaluate(currentTheme => {
        const root = document.documentElement;
        const oldTheme = root.dataset.theme;
        root.dataset.theme = currentTheme;
        try {
          const shell = document.querySelector(".workspace-shell");
          const sidebar = shell.querySelector(".sidebar");
          const main = shell.querySelector(".content");
          const style = el => getComputedStyle(el).backgroundColor;
          return {
            shellHeight: Math.round(shell.getBoundingClientRect().height),
            shellPosition: getComputedStyle(shell).position,
            rootBackground: style(root),
            sidebarBackground: style(sidebar),
            bodyBackground: style(document.body),
            mainBackground: style(main),
            shellBackground: style(shell),
          };
        } finally {
          root.dataset.theme = oldTheme;
        }
      }, theme);
      assert.ok(safeArea.shellHeight >= 720, `${theme}: native document reaches full viewport`);
      assert.equal(safeArea.shellPosition, "relative", `${theme}: no fixed clipping below Safari toolbar`);
      assert.notEqual(safeArea.rootBackground, "rgba(0, 0, 0, 0)");
      assert.equal(safeArea.sidebarBackground, safeArea.rootBackground,
        `${theme}: opaque sidebar matches the shared surface`);
      for (const layer of ["bodyBackground", "mainBackground", "shellBackground"]) {
        assert.equal(safeArea[layer], "rgba(0, 0, 0, 0)",
          `${theme}: only the root paints the workspace background (${layer})`);
      }
    }

    // iOS 26: строка в нативном документе должна уходить ПОД панель Safari,
    // а при прокрутке до конца последний элемент поднимается над кнопками.
    const underlay = await page.evaluate(() => {
      const root = document.documentElement;
      const shell = document.querySelector(".workspace-shell");
      const sidebar = shell.querySelector(".sidebar");
      const content = shell.querySelector(".workspace-content");
      const row = document.createElement("div");
      row.style.cssText = "height:1400px;flex-shrink:0";
      content.append(row);
      try {
        const before = sidebar.getBoundingClientRect().top;
        window.scrollTo(0, 600);
        const whileScrolling = sidebar.getBoundingClientRect().top;
        window.scrollTo(0, root.scrollHeight);
        return {
          shellPosition: getComputedStyle(shell).position,
          sidebarPosition: getComputedStyle(sidebar).position,
          sidebarTopStable: Math.abs(before - whileScrolling) <= 2,
          documentScrolled: window.scrollY > 100,
          bottomReserve: parseFloat(getComputedStyle(content).paddingBottom),
          finalItemBottom: row.getBoundingClientRect().bottom,
          visibleBottom: window.visualViewport?.height || window.innerHeight,
        };
      } finally {
        row.remove();
        window.scrollTo(0, 0);
      }
    });
    assert.equal(underlay.shellPosition, "relative",
      "native document is painted under the Safari toolbar");
    assert.equal(underlay.sidebarPosition, "sticky");
    assert.ok(underlay.sidebarTopStable, "sidebar stays pinned during document scroll");
    assert.ok(underlay.documentScrolled, "the document itself is the scroll container");
    assert.ok(underlay.bottomReserve >= 104, "last item clears the floating browser controls");
    assert.ok(underlay.finalItemBottom <= underlay.visibleBottom - 72,
      "last item is fully reachable above the Safari controls");

    // Открытый диалог не получает большой browser-bottom padding:
    // composer остаётся над нижней панелью даже при уменьшенном visualViewport.
    const chatUnderlay = await page.evaluate(() => {
      const root = document.documentElement;
      const before = root.style.getPropertyValue("--workspace-viewport-height");
      root.style.setProperty("--workspace-viewport-height", "570px");
      const content = document.querySelector(".workspace-content");
      const list = document.createElement("section");
      list.className = "teacher-branch chat-list workspace-panel";
      list.innerHTML = '<div class="chat-list-actions">Чаты</div><div class="chat-items">Участники</div>';
      const detail = document.createElement("section");
      detail.className = "teacher-branch chat-detail";
      detail.innerHTML = `
        <header class="chat-head"><button class="mobile-chat-back">Назад</button><span>Чат</span></header>
        <div class="messages">${Array(24).fill('<div class="message">Длинная переписка</div>').join("")}</div>
        <form class="chat-composer">
          <textarea placeholder="Сообщение"></textarea>
          <div class="composer-footer">
            <button class="btn primary composer-send" type="submit"><span>Отправить</span></button>
          </div>
        </form>`;
      content.append(list, detail);
      try {
        return {
          layoutHeight: content.getBoundingClientRect().height,
          messagesScrollable: detail.querySelector(".messages").scrollHeight > detail.querySelector(".messages").clientHeight,
          sendBottom: detail.querySelector(".composer-send").getBoundingClientRect().bottom,
          composerBottom: detail.querySelector(".chat-composer").getBoundingClientRect().bottom,
          sidebarHeight: document.querySelector(".sidebar").getBoundingClientRect().height,
          contentTop: content.getBoundingClientRect().top,
          detailRect: detail.getBoundingClientRect().toJSON(),
          composerRect: detail.querySelector(".chat-composer").getBoundingClientRect().toJSON(),
          buttonRect: detail.querySelector(".composer-send").getBoundingClientRect().toJSON(),
          messagesRect: detail.querySelector(".messages").getBoundingClientRect().toJSON(),
          visualViewportHeight: window.visualViewport?.height,
          shellPosition: getComputedStyle(document.querySelector(".workspace-shell")).position,
        };
      } finally {
        list.remove();
        detail.remove();
        if (before) root.style.setProperty("--workspace-viewport-height", before);
        else root.style.removeProperty("--workspace-viewport-height");
      }
    });
    assert.ok(chatUnderlay.layoutHeight <= 570 - chatUnderlay.sidebarHeight + 2,
      "chat scrollport fits inside visible Safari viewport");
    assert.ok(chatUnderlay.messagesScrollable,
      "messages scroll within the available chat viewport");
    assert.ok(chatUnderlay.sendBottom <= 572,
      `send button remains above Safari controls: ${JSON.stringify(chatUnderlay)}`);
    assert.ok(chatUnderlay.composerBottom <= 572,
      "composer remains inside visible viewport");

    // Чат: одно двухстрочное поле отправки на телефоне, планшете и Desktop.
    // Поле увеличено по высоте; вложение и текст кнопки всегда доступны.
    for (const { width, height } of [
      { width: 390, height: 720 }, { width: 390, height: 430 },
      { width: 768, height: 650 }, { width: 1280, height: 800 },
    ]) {
      await page.setViewportSize({ width, height });
      await page.waitForFunction(() => {
        const vv = window.visualViewport;
        const shell = document.querySelector(".workspace-shell");
        if (!shell) return false;
        if (matchMedia("(max-width: 1024px) and (display-mode: browser)").matches) {
          return getComputedStyle(shell).position === "relative";
        }
        return !vv || Math.abs(shell.getBoundingClientRect().height - vv.height) <= 2;
      });
      const state = await page.evaluate(() => {
        const content = document.querySelector(".workspace-content");
        const list = document.createElement("section");
        list.className = "teacher-branch chat-list workspace-panel";
        list.innerHTML = '<div class="chat-list-actions">Диалоги</div><div class="chat-items">Личные</div>';
        const detail = document.createElement("section");
        detail.className = "teacher-branch chat-detail";
        detail.innerHTML = `
          <header class="chat-head"><button class="mobile-chat-back">Назад</button><span>Чат</span></header>
          <div class="messages">${Array(30).fill('<div class="message">Текст сообщения для проверки прокрутки</div>').join("")}</div>
          <form class="chat-composer">
            <textarea placeholder="Сообщение"></textarea>
            <div class="composer-footer">
              <div class="composer-tools">
                <label class="attach-control ui-icon-button" aria-label="Прикрепить файл">
                  <svg aria-hidden="true" viewBox="0 0 24 24"><path d="M8 12h8"/></svg>
                  <input type="file">
                </label>
              </div>
              <button class="btn primary composer-send" type="submit"><span>Отправить</span></button>
            </div>
          </form>`;
        content.append(list, detail);
        try {
          const vv = window.visualViewport;
          const limit = (vv?.offsetTop || 0) + (vv?.height || window.innerHeight);
          const messages = detail.querySelector(".messages");
          const button = detail.querySelector(".composer-send");
          const composer = detail.querySelector(".chat-composer");
          const composerInput = composer.querySelector("textarea");
          const composerFooter = composer.querySelector(".composer-footer");
          const attach = composer.querySelector(".attach-control");
          const sendLabel = composer.querySelector(".composer-send span");
          const before = messages.scrollTop;
          messages.scrollTop = messages.scrollHeight;
          return {
            viewportBottom: limit,
            detailBottom: detail.getBoundingClientRect().bottom,
            composerBottom: composer.getBoundingClientRect().bottom,
            buttonBottom: button.getBoundingClientRect().bottom,
            buttonTop: button.getBoundingClientRect().top,
            messagesScroll: messages.scrollTop,
            messagesOverflow: getComputedStyle(messages).overflowY,
            contentScroll: content.scrollTop,
            inputHeight: composerInput.getBoundingClientRect().height,
            footerTop: composerFooter.getBoundingClientRect().top,
            textareaBottom: composerInput.getBoundingClientRect().bottom,
            attachHeight: attach.getBoundingClientRect().height,
            sendHeight: button.getBoundingClientRect().height,
            sendLabelVisible: getComputedStyle(sendLabel).display !== "none",
            contentRect: content.getBoundingClientRect().toJSON(),
            shellRect: document.querySelector(".workspace-shell").getBoundingClientRect().toJSON(),
            sidebarRect: document.querySelector(".sidebar").getBoundingClientRect().toJSON(),
            declaredSidebarHeight: getComputedStyle(document.querySelector(".workspace-shell")).getPropertyValue("--workspace-sidebar-height"),
          };
        } finally {
          detail.remove();
          list.remove();
        }
      });
      assert.ok(state.inputHeight >= 50, `${width}px: composer text field remains enlarged`);
      assert.ok(state.footerTop >= state.textareaBottom - 1,
        `${width}px: actions sit below the message field on every screen`);
      assert.ok(state.attachHeight >= 40 && state.sendHeight >= 40,
        `${width}px: attachment and send have comfortable touch targets`);
      assert.equal(state.sendLabelVisible, width >= 1025,
        `${width}px: compact mobile send icon and labeled desktop send button`);
      assert.ok(state.detailBottom <= state.viewportBottom + 2,
        `${width}x${height}: chat fits inside visible viewport ${JSON.stringify(state)}`);
      assert.ok(state.composerBottom <= state.viewportBottom + 2,
        `${width}x${height}: composer stays above browser controls`);
      assert.ok(state.buttonBottom <= state.viewportBottom + 2,
        `${width}x${height}: send button is visible`);
      assert.ok(state.buttonTop >= 0, `${width}x${height}: send button is not clipped on top`);
      assert.equal(state.messagesOverflow, "auto");
      assert.ok(state.messagesScroll > 0, `${width}x${height}: messages scroll independently`);
      assert.equal(state.contentScroll, 0, `${width}x${height}: chat does not scroll whole workspace`);
    }
    await page.setViewportSize({ width: 1280, height: 720 });

    // Пользователи: поиск, сортировка, добавление и счётчик выглядят как единая панель.
    for (const width of [390, 1280]) {
      await page.setViewportSize({ width, height: 800 });
      for (const theme of ["light", "dark-soft"]) {
        const result = await page.evaluate(currentTheme => {
          const previous = document.documentElement.dataset.theme;
          document.documentElement.dataset.theme = currentTheme;
          const fixture = document.createElement("div");
          fixture.className = "toolbar user-toolbar";
          fixture.style.cssText = "position:fixed;left:0;top:0;visibility:hidden;pointer-events:none;width:100%";
          fixture.innerHTML = `
            <div class="search workspace-search ui-toolbar-control"><input aria-label="Поиск" /></div>
            <span class="ui-toolbar-select user-sort-field"><select class="ui-toolbar-control ui-toolbar-select-native user-sort"><option>Сначала ученики</option></select></span>
            <button class="btn primary user-add-btn ui-toolbar-control">Добавить</button>
            <span class="user-total ui-toolbar-control ui-toolbar-total">Всего <b class="chat-tab-count">11</b></span>
          `;
          document.body.append(fixture);
          const styles = [...fixture.children].map(element => {
            const style = getComputedStyle(element);
            return { radius: style.borderTopLeftRadius, height: Math.round(element.getBoundingClientRect().height) };
          });
          const rows = [...fixture.children].map(element => Math.round(element.getBoundingClientRect().top));
          fixture.remove();
          document.documentElement.dataset.theme = previous;
          return { styles, rows };
        }, theme);
        assert.deepEqual(result.styles.map(x => x.radius), ["9px", "9px", "9px", "9px"],
          `${width}px ${theme}: all four toolbar controls share the same radius`);
        assert.deepEqual(result.styles.map(x => x.height), [42, 42, 42, 42],
          `${width}px ${theme}: toolbar controls have identical heights`);
        assert.equal(result.rows[0], result.rows[2], `${width}px ${theme}: search and add share a row`);
        assert.equal(result.rows[1], result.rows[3], `${width}px ${theme}: sort and total share a row`);
      }
    }
    await page.setViewportSize({ width: 1280, height: 720 });

    // Единая и более контрастная подсветка выбранного раздела, вкладки и чата,
    // включая границу перестроения навигации 1024/1025 px.
    for (const width of [390, 1024, 1025, 1280]) {
      await page.setViewportSize({ width, height: 800 });
      for (const theme of ["light", "dark-soft"]) {
        const state = await page.evaluate(nextTheme => {
          const root = document.documentElement;
          const previous = root.dataset.theme;
          root.dataset.theme = nextTheme;
          const host = document.createElement("div");
          host.className = "workspace-shell";
          host.style.cssText = "position:fixed;top:0;left:0;width:100%;height:100%;visibility:hidden;pointer-events:none";
          host.innerHTML = `
            <aside class="sidebar">
              <nav>
                <button class="ui-menu-control" aria-current="page">Диалоги</button>
                <button class="ui-menu-control">Пользователи</button>
              </nav>
            </aside>
            <section class="chat-list">
              <div class="chat-section-tabs ui-toolbar-control ui-toolbar-segmented">
                <button class="chat-section-tab ui-toolbar-tab" aria-pressed="true">Личные</button>
                <button class="chat-section-tab ui-toolbar-tab" aria-pressed="false">Участники</button>
              </div>
              <div class="chat-items">
                <button class="student-card chat-item selected">Активный чат</button>
                <button class="student-card chat-item">Неактивный чат</button>
              </div>
            </section>
          `;
          document.body.append(host);
          const read = selector => {
            const computed = getComputedStyle(host.querySelector(selector));
            return { background: computed.backgroundColor,
              border: computed.borderTopColor, color: computed.color };
          };
          try {
            return {
              navigation: read(".sidebar nav [aria-current]"),
              navigationInactive: read(".sidebar nav button:not([aria-current])"),
              tab: read(".chat-section-tab[aria-pressed=true]"),
              tabInactive: read(".chat-section-tab[aria-pressed=false]"),
              chat: read(".chat-item.selected"),
              chatInactive: read(".chat-item:not(.selected)"),
              shellRadius: getComputedStyle(host).borderTopLeftRadius,
              sidebarRadius: getComputedStyle(host.querySelector(".sidebar")).borderTopLeftRadius,
              menuRadius: getComputedStyle(host.querySelector(".ui-menu-control")).borderTopLeftRadius,
              tabWrapperRadius: getComputedStyle(host.querySelector(".ui-toolbar-segmented")).borderTopLeftRadius,
              innerTabRadius: getComputedStyle(host.querySelector(".chat-section-tab")).borderTopLeftRadius,
              tabWrapperOverflow: getComputedStyle(host.querySelector(".ui-toolbar-segmented")).overflow,
            };
          } finally {
            host.remove();
            root.dataset.theme = previous;
          }
        }, theme);
        assert.deepEqual(state.navigation, state.tab,
          `${width}px ${theme}: sidebar and chat tabs share selected color/border/text`);
        assert.deepEqual(state.navigation, state.chat,
          `${width}px ${theme}: selected conversations share selected palette`);
        for (const [active, inactive] of [
          [state.navigation, state.navigationInactive],
          [state.tab, state.tabInactive],
          [state.chat, state.chatInactive],
        ]) {
          assert.notEqual(active.background, inactive.background,
            `${width}px ${theme}: selected background must be visible`);
          assert.notEqual(active.border, inactive.border,
            `${width}px ${theme}: selected border must be visible`);
        }
        assert.equal(state.shellRadius, "0px", `${width}px ${theme}: no white shell corner slivers`);
        assert.equal(state.sidebarRadius, "0px", `${width}px ${theme}: no sidebar corner slivers`);
        assert.equal(state.menuRadius, "9px", `${width}px ${theme}: navigation and tab radii match`);
        assert.equal(state.tabWrapperRadius, state.menuRadius);
        assert.equal(state.innerTabRadius, state.menuRadius);
        assert.equal(state.tabWrapperOverflow, "hidden");
      }
    }
    await page.setViewportSize({ width: 1280, height: 800 });

    // Выделение переписки — один CSS для учителя, администратора и ученика.
    // Используем реальные классы кабинетов и сверяем с панелью преподавателя.
    for (const width of [390, 760, 1024, 1025, 1280]) {
      await page.setViewportSize({ width, height: 800 });
      for (const theme of ["light", "dark-soft"]) {
        const styles = await page.evaluate(currentTheme => {
          const root = document.documentElement;
          const oldTheme = root.dataset.theme;
          root.dataset.theme = currentTheme;
          const result = {};
          try {
            for (const role of ["teacher", "admin", "student"]) {
              const fixture = document.createElement("div");
              fixture.className = "workspace-shell workspace-" + role;
              fixture.style.cssText = "position:fixed;top:0;left:0;visibility:hidden;pointer-events:none;z-index:-1;width:270px";
              fixture.innerHTML = `
                <section class="chat-list">
                  <div class="chat-items">
                    <button class="student-card chat-item selected" aria-pressed="true">Выбран</button>
                    <button class="student-card chat-item" aria-pressed="true">Выбран по aria-pressed</button>
                    <button class="student-card chat-item" aria-pressed="false">Другой</button>
                  </div>
                </section>
              `;
              document.body.append(fixture);
              try {
                const buttons = [...fixture.querySelectorAll(".chat-item")];
                result[role] = buttons.map(button => {
                  const style = getComputedStyle(button);
                  return {
                    background: style.backgroundColor,
                    border: style.borderTopColor,
                    color: style.color,
                    shadow: style.boxShadow,
                  };
                });
              } finally {
                fixture.remove();
              }
            }
            return result;
          } finally {
            root.dataset.theme = oldTheme;
          }
        }, theme);
        for (const role of ["admin", "student"]) {
          assert.deepEqual(styles[role], styles.teacher,
            `${width}px ${theme}: dialog selection matches teacher palette for ${role}`);
        }
        assert.deepEqual(styles.teacher[0], styles.teacher[1],
          `${width}px ${theme}: aria-pressed and selected class have identical highlights`);
        assert.notEqual(styles.teacher[0].background, styles.teacher[2].background,
          `${width}px ${theme}: selected dialog has distinguishable background`);
        assert.notEqual(styles.teacher[0].border, styles.teacher[2].border,
          `${width}px ${theme}: selected dialog has distinguishable border`);
      }
    }
    await page.setViewportSize({ width: 1280, height: 800 });

    // Переключатель диалогов и кнопка создания всегда остаются в одной строке.
    for (const width of [320, 390, 760, 1280]) {
      await page.setViewportSize({ width, height: 800 });
      for (const theme of ["light", "dark-soft"]) {
        const controls = await page.evaluate(selectedTheme => {
          const previous = document.documentElement.dataset.theme;
          document.documentElement.dataset.theme = selectedTheme;
          const host = document.createElement("div");
          host.className = "workspace-shell";
          host.style.cssText = "position:fixed;left:0;top:0;visibility:hidden;pointer-events:none";
          const panelWidth = Math.min(270, window.innerWidth - 20);
          host.innerHTML = `
            <div class="chat-list workspace-panel" style="box-sizing:border-box;width:${panelWidth}px;padding:12px">
              <div class="chat-list-actions workspace-control-row">
                <div class="chat-section-tabs ui-toolbar-control ui-toolbar-segmented" role="group">
                  <button class="chat-section-tab ui-toolbar-tab" aria-pressed="true">Участники</button>
                  <button class="chat-section-tab ui-toolbar-tab" aria-pressed="false">Личные<span class="chat-tab-count">12</span></button>
                </div>
                <button class="icon-btn ui-icon-button personal-chat-create ui-toolbar-icon" aria-label="Новый диалог">+</button>
              </div>
            </div>
          `;
          document.body.append(host);
          const actions = host.querySelector(".chat-list-actions");
          const tabs = [...host.querySelectorAll(".chat-section-tab")];
          const create = host.querySelector(".personal-chat-create");
          const selected = getComputedStyle(tabs[0]);
          const other = getComputedStyle(tabs[1]);
          const result = {
            rowWidth: actions.clientWidth,
            rowScroll: actions.scrollWidth,
            tabWidths: tabs.map(el => [el.clientWidth, el.scrollWidth]),
            tabHeights: tabs.map(el => Math.round(el.getBoundingClientRect().height)),
            tabWhiteSpace: tabs.map(el => getComputedStyle(el).whiteSpace),
            newWidth: Math.round(create.getBoundingClientRect().width),
            newHeight: Math.round(create.getBoundingClientRect().height),
            verticalGap: Math.abs(create.getBoundingClientRect().top
              + create.getBoundingClientRect().height / 2
              - actions.getBoundingClientRect().top - actions.getBoundingClientRect().height / 2),
            selectedBackground: selected.backgroundColor,
            inactiveBackground: other.backgroundColor,
          };
          host.remove();
          document.documentElement.dataset.theme = previous;
          return result;
        }, theme);
        assert.ok(controls.rowScroll <= controls.rowWidth + 1,
          `${theme} ${width}px: действия не выходят за границы`);
        for (let i = 0; i < controls.tabWidths.length; i++) {
          assert.equal(controls.tabWhiteSpace[i], "nowrap",
            `${theme} ${width}px: без переноса текста вкладки ${i + 1}`);
          assert.ok(controls.tabWidths[i][1] <= controls.tabWidths[i][0] + 1,
            `${theme} ${width}px: надпись вкладки ${i + 1} помещается`);
        }
        assert.equal(controls.tabHeights[0], controls.tabHeights[1]);
        assert.equal(controls.newWidth, 42);
        assert.equal(controls.newHeight, 42);
        assert.ok(controls.verticalGap <= 1);
        assert.notEqual(controls.selectedBackground, controls.inactiveBackground);
      }
    }
    await page.setViewportSize({ width: 1280, height: 800 });

    // Реальный сенсорный viewport: проверяем, что мобильные правила не
    // превращают активные фиолетовые вкладки в серые. CSS одинаков для ролей.
    const touchContext = await browser.newContext({
      viewport: { width: 390, height: 800 },
      isMobile: true,
      hasTouch: true,
      deviceScaleFactor: 2,
    });
    try {
      const touchPage = await touchContext.newPage();
      await touchPage.goto(APP_URL);
      await touchPage.waitForFunction(() => !!document.querySelector("#root")?.firstElementChild);
      for (const width of [320, 390, 760, 1024, 1025, 1280]) {
        await touchPage.setViewportSize({ width, height: 800 });
        for (const theme of ["light", "dark-soft"]) {
          let reference;
          for (const role of ["admin", "teacher", "student"]) {
            const state = await touchPage.evaluate(({ role, theme }) => {
              const root = document.documentElement;
              const previous = root.dataset.theme;
              root.dataset.theme = theme;
              const host = document.createElement("div");
              host.className = "workspace-shell workspace-" + role;
              host.style.cssText = "position:fixed;inset:0;width:100vw;height:800px;visibility:hidden;pointer-events:none;z-index:-1";
              host.innerHTML = [
                '<aside class="sidebar"><nav><button class="ui-menu-control" aria-current="page">Диалоги</button></nav></aside>',
                '<section class="chat-list workspace-panel" style="box-sizing:border-box;width:270px;padding:12px">',
                '<div class="chat-list-actions workspace-control-row">',
                '<div class="chat-section-tabs ui-toolbar-control ui-toolbar-segmented" role="group">',
                '<button class="chat-section-tab ui-toolbar-tab" aria-pressed="true">Участники</button>',
                '<button class="chat-section-tab ui-toolbar-tab" aria-pressed="false">Личные<span class="chat-tab-count">12</span></button>',
                '</div><button class="icon-btn ui-icon-button personal-chat-create ui-toolbar-icon">+</button>',
                '</div></section>',
              ].join("");
              host.querySelector(".chat-list").style.width = Math.min(270, window.innerWidth - 20) + "px";
              document.body.append(host);
              try {
                const read = selector => {
                  const el = host.querySelector(selector);
                  const css = getComputedStyle(el);
                  const rect = el.getBoundingClientRect();
                  return {
                    background: css.backgroundColor,
                    border: css.borderTopColor,
                    color: css.color,
                    height: Math.round(rect.height),
                    width: Math.round(rect.width),
                    radius: css.borderTopLeftRadius,
                    overflow: el.scrollWidth - el.clientWidth,
                  };
                };
                return {
                  media: matchMedia("(hover: none), (pointer: coarse)").matches,
                  nav: read(".sidebar [aria-current=page]"),
                  group: read(".chat-section-tabs"),
                  active: read(".chat-section-tab[aria-pressed=true]"),
                  inactive: read(".chat-section-tab[aria-pressed=false]"),
                  create: read(".personal-chat-create"),
                  row: read(".chat-list-actions"),
                };
              } finally {
                host.remove();
                root.dataset.theme = previous;
              }
            }, { role, theme });
            assert.equal(state.media, true, "touch rules must be active");
            assert.deepEqual(
              [state.active.background, state.active.border, state.active.color],
              [state.nav.background, state.nav.border, state.nav.color],
              `${theme} ${width}px ${role}: active tabs use same purple as sidebar`,
            );
            assert.notEqual(state.active.background, state.inactive.background,
              `${theme} ${width}px ${role}: selected segment is visibly distinct`);
            assert.equal(state.active.width, state.inactive.width,
              `${theme} ${width}px ${role}: segments have equal widths`);
            assert.equal(state.active.height, state.inactive.height,
              `${theme} ${width}px ${role}: segments have equal heights`);
            assert.equal(state.group.height, 42);
            assert.equal(state.create.height, 42);
            assert.equal(state.create.width, 42);
            assert.equal(state.group.radius, "9px");
            assert.ok(state.row.overflow <= 1, `${width}px: chat buttons fit the row`);
            assert.ok(state.active.overflow <= 1 && state.inactive.overflow <= 1,
              `${width}px: chat button labels and unread badge fit`);
            const colors = { nav: state.nav, group: state.group, active: state.active, inactive: state.inactive };
            if (!reference) reference = colors;
            else assert.deepEqual(colors, reference,
              `${theme} ${width}px: shared chat colors independent of role`);
          }
        }
      }
    } finally {
      await touchContext.close();
    }
    await page.setViewportSize({ width: 1280, height: 800 });

    // Одна геометрия карточек, отступов и рядов на телефоне и десктопе.
    for (const width of [390, 1280]) {
      await page.setViewportSize({ width, height: 800 });
      for (const theme of ["light", "dark-soft"]) {
        const layout = await page.evaluate(currentTheme => {
          const root = document.documentElement;
          const old = root.dataset.theme;
          root.dataset.theme = currentTheme;
          const fixture = document.createElement("div");
          fixture.innerHTML = `
            <section class="workspace-panel users-panel">
              <div class="toolbar user-toolbar">
                <div class="search workspace-search ui-toolbar-control">Поиск</div>
                <span class="ui-toolbar-select user-sort-field"><select class="ui-toolbar-control ui-toolbar-select-native user-sort"><option>Сначала ученики</option></select></span>
                <button class="btn primary user-add-btn ui-toolbar-control">Добавить</button>
                <span class="user-total ui-toolbar-control ui-toolbar-total">Всего</span>
              </div>
              <div class="user-list">Пользователь</div>
            </section>
            <section class="teacher-branch chat-list workspace-panel">
              <div class="chat-list-actions workspace-control-row">
                <div class="chat-section-tabs ui-toolbar-control ui-toolbar-segmented">Участники</div>
                <button class="icon-btn ui-icon-button personal-chat-create ui-toolbar-icon">+</button>
              </div>
              <div class="chat-list-filters workspace-control-row">
                <label class="search workspace-search ui-toolbar-control">Поиск</label>
                <label class="chat-filter"><span class="ui-toolbar-select chat-filter-field"><select class="ui-toolbar-control ui-toolbar-select-native"><option>Все личные</option></select></span></label>
              </div>
              <div class="chat-items">Диалог</div>
            </section>
          `;
          document.querySelector(".workspace-content").append(fixture);
          try {
            const stats = el => {
              const st = getComputedStyle(el);
              return {
                padding: st.paddingTop, gap: st.rowGap, radius: st.borderTopLeftRadius,
                border: st.borderTopWidth, background: st.backgroundColor,
              };
            };
            const user = fixture.querySelector(".users-panel");
            const chat = fixture.querySelector(".chat-list");
            const toolbar = fixture.querySelector(".user-toolbar");
            const actions = fixture.querySelector(".chat-list-actions");
            const filters = fixture.querySelector(".chat-list-filters");
            return { user: stats(user), chat: stats(chat),
              userGap: getComputedStyle(toolbar).rowGap,
              actionsGap: getComputedStyle(actions).columnGap,
              filtersGap: getComputedStyle(filters).columnGap,
              actionsDisplay: getComputedStyle(actions).display,
              filtersDisplay: getComputedStyle(filters).display };
          } finally {
            fixture.remove();
            root.dataset.theme = old;
          }
        }, theme);
        assert.deepEqual(layout.user, layout.chat, `${width}px ${theme}: same panel style`);
        assert.equal(layout.userGap, layout.actionsGap, `${width}px ${theme}: same control spacing`);
        assert.equal(layout.userGap, layout.filtersGap, `${width}px ${theme}: same row spacing`);
        assert.equal(layout.actionsDisplay, "grid");
        assert.equal(layout.filtersDisplay, "grid");
      }
    }
    await page.setViewportSize({ width: 1280, height: 800 });

    // Общие реальные CSS-классы органов управления обеих вкладок.
    for (const width of [390, 1280]) {
      await page.setViewportSize({ width, height: 800 });
      for (const theme of ["light", "dark-soft"]) {
        const controls = await page.evaluate(currentTheme => {
          const original = document.documentElement.dataset.theme;
          document.documentElement.dataset.theme = currentTheme;
          const fixture = document.createElement("div");
          fixture.innerHTML = `
            <div class="toolbar user-toolbar">
              <div class="search workspace-search ui-toolbar-control"><input placeholder="Поиск по имени"></div>
              <span class="ui-toolbar-select user-sort-field"><select class="ui-toolbar-control ui-toolbar-select-native user-sort"><option>Сначала ученики</option></select></span>
              <button class="btn primary user-add-btn ui-toolbar-control">Добавить</button>
              <span class="user-total ui-toolbar-control ui-toolbar-total">Всего <b>11</b></span>
            </div>
            <section class="teacher-branch chat-list workspace-panel">
              <div class="chat-list-actions workspace-control-row">
                <div class="chat-section-tabs ui-toolbar-control ui-toolbar-segmented">
                  <button class="chat-section-tab ui-toolbar-tab" aria-pressed="true">Участники</button>
                  <button class="chat-section-tab ui-toolbar-tab" aria-pressed="false">Личные</button>
                </div>
                <button class="icon-btn ui-icon-button personal-chat-create ui-toolbar-icon" aria-label="Новый диалог">+</button>
              </div>
              <div class="chat-list-filters workspace-control-row">
                <label class="search workspace-search ui-toolbar-control"><input placeholder="Поиск по имени"></label>
                <label class="chat-filter"><span class="ui-toolbar-select chat-filter-field"><select class="ui-toolbar-control ui-toolbar-select-native"><option>Все личные</option></select></span></label>
              </div>
            </section>
          `;
          document.querySelector(".workspace-content").append(fixture);
          try {
            const measure = selector => {
              const el = fixture.querySelector(selector);
              const style = getComputedStyle(el);
              return {
                height: Math.round(el.getBoundingClientRect().height),
                radius: style.borderTopLeftRadius,
                fontSize: style.fontSize,
                background: style.backgroundColor,
              };
            };
            return {
              userSearch: measure(".user-toolbar .workspace-search"),
              userSort: measure(".user-sort"),
              userAdd: measure(".user-add-btn"),
              userTotal: measure(".user-total"),
              chatSearch: measure(".chat-list .workspace-search"),
              chatFilter: measure(".chat-filter select"),
              chatTabs: measure(".chat-section-tabs"),
              chatTab: measure(".chat-section-tab"),
              chatAdd: measure(".personal-chat-create"),
            };
          } finally {
            fixture.remove();
            document.documentElement.dataset.theme = original;
          }
        }, theme);
        for (const name of ["userSearch", "userSort", "userAdd", "userTotal",
          "chatSearch", "chatFilter", "chatTabs", "chatAdd"]) {
          assert.equal(controls[name].height, 42, `${width}px ${theme}: ${name} height`);
          assert.equal(controls[name].radius, "9px", `${width}px ${theme}: ${name} radius`);
        }
        for (const name of ["userSearch", "userSort", "userAdd", "userTotal",
          "chatSearch", "chatFilter", "chatTab"]) {
          assert.equal(controls[name].fontSize, "13px", `${width}px ${theme}: ${name} font size`);
        }
        assert.equal(controls.userSearch.background, controls.chatSearch.background,
          `${width}px ${theme}: search backgrounds match`);
        assert.equal(controls.userSort.background, controls.chatFilter.background,
          `${width}px ${theme}: filter backgrounds match`);
      }
    }
    await page.setViewportSize({ width: 1280, height: 800 });

    // Нативные браузерные select выглядят одинаково в обеих вкладках без SVG-стрелок.
    for (const width of [390, 1280]) {
      await page.setViewportSize({ width, height: 800 });
      for (const theme of ["light", "dark-soft"]) {
        const styles = await page.evaluate(currentTheme => {
          const old = document.documentElement.dataset.theme;
          document.documentElement.dataset.theme = currentTheme;
          const host = document.createElement("div");
          host.innerHTML = `
            <span class="ui-toolbar-select user-sort-field">
              <select class="ui-toolbar-control ui-toolbar-select-native user-sort"><option>Сначала ученики</option></select>
            </span>
            <span class="ui-toolbar-select chat-filter-field">
              <select class="ui-toolbar-control ui-toolbar-select-native"><option>Все личные</option></select>
            </span>
          `;
          document.querySelector(".workspace-content").append(host);
          try {
            return [...host.querySelectorAll("select")].map(el => {
              const s = getComputedStyle(el);
              return {
                height: Math.round(el.getBoundingClientRect().height),
                radius: s.borderTopLeftRadius,
                appearance: s.appearance,
                arrowVisible: Boolean(el.nextElementSibling) && getComputedStyle(el.nextElementSibling).display !== "none",
              };
            });
          } finally {
            host.remove();
            document.documentElement.dataset.theme = old;
          }
        }, theme);
        assert.deepEqual(styles[0], styles[1], `${width}px ${theme}: одинаковое оформление select`);
        assert.equal(styles[0].height, 42);
        assert.equal(styles[0].radius, "9px");
        assert.notEqual(styles[0].appearance, "none");
        assert.equal(styles[0].arrowVisible, false);
      }
    }
    await page.setViewportSize({ width: 1280, height: 800 });

    // HTML <dialog> находится в нативном top layer и использует одну геометрию
    // кнопок создания, редактирования и выдачи кода на всех размерах.
    for (const width of [320, 390, 768, 1280]) {
      await page.setViewportSize({ width, height: 800 });
      const dialogGeometry = await page.evaluate(() => {
        const dialog = document.createElement("dialog");
        dialog.className = "modal native-dialog participant-profile-modal";
        dialog.innerHTML = `
          <div class="modal-head"><h2>Редактировать участника</h2></div>
          <div class="stack"><label>Имя<input value="Иван Иванов"></label>
          <div class="panel-access-value"><b>XXXX-XXXX</b>
            <button class="btn outline password-code-refresh">Новый код</button></div></div>
          <div class="modal-actions">
            <button class="btn ghost">Отмена</button>
            <button class="icon-btn ui-icon-button ui-icon-button--danger">×</button>
            <button class="btn primary">Сохранить</button>
          </div>`;
        document.body.append(dialog);
        dialog.showModal();
        try {
          const actions = [...dialog.querySelectorAll(".modal-actions > button")];
          const refresh = dialog.querySelector(".password-code-refresh");
          const bounds = dialog.getBoundingClientRect();
          const last = actions.at(-1).getBoundingClientRect();
          return {
            modal: dialog.matches(":modal"),
            tag: dialog.tagName,
            width: bounds.width,
            actionHeights: actions.map(button => Math.round(button.getBoundingClientRect().height)),
            refreshHeight: Math.round(refresh.getBoundingClientRect().height),
            rightInset: Math.round(bounds.right - last.right),
          };
        } finally {
          dialog.close();
          dialog.remove();
        }
      });
      assert.equal(dialogGeometry.tag, "DIALOG");
      assert.ok(dialogGeometry.modal, `${width}px: HTMLDialogElement is in browser top layer`);
      assert.ok(dialogGeometry.width <= width - 16, `${width}px: dialog fits screen`);
      assert.deepEqual(dialogGeometry.actionHeights, [44, 44, 44],
        `${width}px: right-aligned action buttons are equally tall`);
      assert.equal(dialogGeometry.refreshHeight, 44,
        `${width}px: new access code button matches action heights`);
      assert.ok(dialogGeometry.rightInset >= 10 && dialogGeometry.rightInset <= 35,
        `${width}px: buttons are aligned to the right`);
    }
    await page.setViewportSize({ width: 1280, height: 800 });

    // Проверяем общий квадратный контур кнопок во всех кабинетах, модальных окнах и темах.
    const originalViewport = page.viewportSize();
    for (const width of [390, 1280]) {
      await page.setViewportSize({ width, height: 800 });
      for (const theme of ["light", "dark-soft"]) {
        const styles = await page.evaluate(currentTheme => {
          const previousTheme = document.documentElement.dataset.theme;
          document.documentElement.dataset.theme = currentTheme;
          const sample = document.createElement("div");
          sample.className = "workspace-content";
          sample.style.cssText = "position:fixed;top:0;left:0;z-index:-1;visibility:hidden";
          sample.innerHTML = `
            <div class="admin-card"></div>
            <div class="teacher-card"><div class="person-actions">
              <button class="icon-btn ui-icon-button danger-icon teacher-collapse-btn"></button>
              <button class="icon-btn ui-icon-button"></button>
            </div></div>
            <div class="student-card">
              <button class="icon-btn ui-icon-button graph-person-action"></button>
            </div>
            <div class="user-actions"><button class="icon-btn ui-icon-button user-action-btn edit-btn"></button></div>
            <div class="modal"><div class="modal-head"><button class="icon-btn ui-icon-button"></button></div></div>
            <div class="graph-board-object-actions"><button class="icon-btn ui-icon-button ui-icon-button--compact"></button></div>
          `;
          document.body.appendChild(sample);
          const selectors = [
            ".teacher-card .teacher-collapse-btn", ".teacher-card .person-actions .ui-icon-button:not(.danger-icon)",
            ".student-card .graph-person-action", ".user-actions .edit-btn",
            ".modal-head .ui-icon-button", ".graph-board-object-actions .ui-icon-button",
          ];
          const result = selectors.map(selector => {
            const el = sample.querySelector(selector);
            const style = getComputedStyle(el);
            const rect = el.getBoundingClientRect();
            return {
              selector, width: Math.round(rect.width), height: Math.round(rect.height),
              border: style.borderTopWidth, borderStyle: style.borderTopStyle,
              radius: parseFloat(style.borderTopLeftRadius), background: style.backgroundColor,
            };
          });
          sample.remove();
          document.documentElement.dataset.theme = previousTheme;
          return result;
        }, theme);
        for (const style of styles) {
          const expected = style.selector.includes("graph-board-object") ? 30 : 34;
          assert.equal(style.width, expected, `${theme} ${width}px ${style.selector} width`);
          assert.equal(style.height, expected, `${theme} ${width}px ${style.selector} height`);
          assert.equal(style.border, "1px", `${theme} ${width}px ${style.selector} border`);
          assert.equal(style.borderStyle, "solid", `${theme} ${width}px ${style.selector} border style`);
          assert.ok(style.radius >= 8, `${theme} ${width}px ${style.selector} border radius`);
          assert.notEqual(style.background, "rgba(0, 0, 0, 0)", `${theme} ${width}px ${style.selector} background`);
        }
      }
    }
    // Назначение ученика — обычное действие, включённые уведомления имеют цвет выбора.
    for (const width of [390, 760, 1024, 1280]) {
      await page.setViewportSize({ width, height: 800 });
      for (const theme of ["light", "dark-soft"]) {
        const styles = await page.evaluate(nextTheme => {
          const root = document.documentElement;
          const oldTheme = root.dataset.theme;
          root.dataset.theme = nextTheme;
          const host = document.createElement("div");
          host.className = "workspace-shell workspace-admin";
          host.style.cssText = "position:fixed;left:0;top:0;width:600px;height:auto;opacity:0;pointer-events:none;z-index:-1";
          host.innerHTML = `
            <header class="topbar"><div class="topbar-actions">
              <button class="push-toggle active ui-icon-button" aria-pressed="true">Уведомления</button>
            </div></header>
            <aside class="sidebar"><div class="mobile-quick-actions">
              <button class="push-toggle active ui-icon-button" aria-pressed="true">Уведомления</button>
            </div></aside>
            <div class="workspace-content"><div class="admin-card"></div>
              <div class="grid"><section class="teacher-branch">
                <button class="add-student">Назначить ученика</button>
              </section></div>
              <div class="unassigned-grid"><div class="unassigned-student-card">
                <div class="unassigned-student-actions">
                  <button class="btn outline">Назначить</button>
                </div></div></div>
            </div>
          `;
          document.body.append(host);
          const prop = el => {
            const css = getComputedStyle(el);
            return { background: css.backgroundColor, border: css.borderTopColor, color: css.color };
          };
          const reference = document.createElement("span");
          reference.style.cssText = "background:var(--ui-selected-bg);border:1px solid var(--ui-selected-border);color:var(--ui-selected-text)";
          const action = document.createElement("span");
          action.style.cssText = "background:var(--ui-control-bg);border:1px solid var(--ui-border);color:var(--muted)";
          host.append(reference, action);
          try {
            return {
              selected: prop(reference),
              action: prop(action),
              add: prop(host.querySelector(".add-student")),
              assign: prop(host.querySelector(".btn.outline")),
              bells: [...host.querySelectorAll(".push-toggle.active")].map(prop),
            };
          } finally {
            host.remove();
            root.dataset.theme = oldTheme;
          }
        }, theme);
        for (const [name, style, expected] of [
          ["Добавить ученика", styles.add, styles.action],
          ["Назначить", styles.assign, styles.action],
          ["Десктопный колокольчик", styles.bells[0], styles.selected],
          ["Мобильный колокольчик", styles.bells[1], styles.selected],
        ]) {
          assert.deepEqual(style, expected, `${width}px ${theme}: ${name}`);
        }
      }
    }
    await page.setViewportSize(originalViewport);

    // Стрелка свёрнутого списка смотрит влево, раскрытого — вниз; кнопка цвета ученика.
    for (const theme of ["light", "dark-soft"]) {
      const state = await page.evaluate(selectedTheme => {
        const previous = document.documentElement.dataset.theme;
        document.documentElement.dataset.theme = selectedTheme;
        const host = document.createElement("div");
        host.className = "workspace-content";
        host.innerHTML = `
          <div class="admin-card"></div>
          <div class="teacher-card"><div class="person-actions">
            <button class="icon-btn ui-icon-button ui-icon-button--student teacher-collapse-btn">
              <svg style="transition:none !important" viewBox="0 0 24 24"><path d="m15 18-6-6 6-6" /></svg>
            </button>
            <button class="icon-btn ui-icon-button ui-icon-button--student teacher-collapse-btn is-expanded">
              <svg style="transition:none !important" viewBox="0 0 24 24"><path d="m15 18-6-6 6-6" /></svg>
            </button>
          </div></div>
        `;
        document.body.appendChild(host);
        const buttons = [...host.querySelectorAll(".teacher-collapse-btn")];
        const result = buttons.map(button => ({
          background: getComputedStyle(button).backgroundColor,
          border: getComputedStyle(button).borderColor,
          color: getComputedStyle(button).color,
          rotation: getComputedStyle(button.querySelector("svg")).transform,
        }));
        host.remove();
        document.documentElement.dataset.theme = previous;
        return result;
      }, theme);
      assert.equal(state[0].rotation, "none", `${theme}: свёрнутый список — стрелка влево`);
      const matrixMatch = /^matrix\(([^)]+)\)$/.exec(state[1].rotation);
      assert.ok(matrixMatch, `${theme}: ожидаем матрицу поворота`);
      const [a, b] = matrixMatch[1].split(",").map(Number);
      assert.ok(Math.abs(a) < .01 && b < -.99,
        `${theme}: открытый список — стрелка вниз`);
      assert.equal(state[0].background, state[1].background);
      assert.equal(state[0].border, state[1].border);
      assert.equal(state[0].color, state[1].color);
      assert.notEqual(state[0].background, "rgba(0, 0, 0, 0)");
    }
    await page.setViewportSize(originalViewport);

    await waitFor(() => pendingPersonalResponses.length === 1);
    assert.equal(pendingPersonalResponses.length, 1,
      "the workspace shell must render before the personal inbox request finishes");
    await page.getByRole("button", { name: "Диалоги" }).click();
    await page.getByRole("button", { name: /Личные/ }).click();
    assert.equal(await page.getByText("Личных диалогов пока нет").count(), 0);
    await page.getByRole("button", { name: "Доски" }).click();
    for (const response of pendingPersonalResponses.splice(0)) {
      response.writeHead(200, { "Content-Type": "application/json" });
      response.end(JSON.stringify([personalChat]));
    }

        await waitFor(() => streams.size === 1 && inboxRequests > 0 && personalRequests > 0);
    await delay(300);
    assert.equal(inboxRequests, 1, "initial conversation list must be requested once");
    assert.equal(personalRequests, 1, "initial personal list must be requested once");
    assert.equal(maxActiveStreams, 1, "only one global SSE connection may be active");

    const summary = unreadCount => ({
      id: 5,
      type: "personal",
      participant: personalChat.participant,
      title: personalChat.title,
      created_at: personalChat.created_at,
      unread_count: unreadCount,
    });
    publish({
      event_id: 101,
      conversation_id: 5,
      conversation_type: "personal",
      action: "upsert",
      summary: summary(4),
    });

    await page.getByRole("button", { name: "Диалоги" }).click();
    await page.getByRole("button", { name: /Личные/ }).click();
    await page.getByLabel("4 непрочитанных личных сообщений").waitFor({ state: "visible" });
    // В фильтре нет лишней подписи, но native select сохраняет доступное имя.
    assert.equal(await page.getByText("Показать", { exact: true }).count(), 0);
    assert.equal(await page.getByRole("combobox", { name: "Фильтр диалогов" }).count(), 1);

    publish({
      event_id: 101,
      conversation_id: 5,
      conversation_type: "personal",
      action: "upsert",
      summary: summary(99),
    });
    await delay(150);
    assert.equal(await page.getByLabel("4 непрочитанных личных сообщений").count(), 1,
      "duplicate event IDs must not apply twice");

    await page.getByRole("button", { name: /Учитель/ }).click();
    await page.getByText("Проверка адресной синхронизации").waitFor({ state: "visible" });
    publish({
      event_id: 102,
      conversation_id: 5,
      conversation_type: "personal",
      action: "read",
      actor_role: "teacher",
      message_ids: [77],
      read_at: "2026-11-21T11:00:00+00:00",
      summary: summary(0),
    });
    await page.getByLabel("Прочитано в UknowApp").waitFor({ state: "visible" });
    await waitFor(() => syncRequests > 0);

    await page.getByRole("button", { name: "Доски" }).click();
    await waitFor(() => streams.size === 1);
    for (const response of [...streams]) response.end();
    await waitFor(() => streams.size === 0);
    publish({
      event_id: 103,
      conversation_id: 5,
      conversation_type: "personal",
      action: "upsert",
      summary: summary(2),
    });

    await waitFor(() => lastEventIds.includes(102), 10000);
    await waitFor(() => streams.size === 1, 10000);
    assert.equal(maxActiveStreams, 1, "reconnect must not create parallel SSE connections");

    await page.getByRole("button", { name: "Диалоги" }).click();
    await page.getByRole("button", { name: /Личные/ }).click();
    await page.getByLabel("2 непрочитанных личных сообщений").waitFor({ state: "visible" });
    assert.equal(inboxRequests, 1, "SSE reconnect must not reload inbox lists when replay is sufficient");
    assert.equal(personalRequests, 1, "SSE reconnect must not reload personal lists when replay is sufficient");
    assert.ok(syncRequests > 0, "opening a dialog and a read event must reconcile only that dialog");
    // SSE: новое сообщение (даже когда читатель прокрутил историю вверх)
    // должно появиться в зоне видимости без скролла всей страницы.
    await page.getByRole("button", { name: /Учитель/ }).click();
    await page.getByText("Проверка адресной синхронизации").waitFor({ state: "visible" });
    await page.locator(".messages").evaluate(el => {
      el.style.height = "120px";
      el.style.maxHeight = "120px";
      el.style.overflowY = "auto";
    });
    syncNewMessages = Array.from({ length: 32 }, (_, index) => ({
      id: index + 78,
      sender: "Учитель",
      sender_role: "teacher",
      can_delete: false,
      content_type: "text",
      text: index === 31 ? "Новое сообщение для автопрокрутки" : "Тестовая строка " + index,
      metadata: {},
      delivery_status: "delivered",
      panel_read_at: null,
      created_at: new Date(Date.parse("2026-11-21T11:01:00Z") + index * 1000).toISOString(),
    }));
    publish({
      event_id: 104,
      conversation_id: 5,
      conversation_type: "personal",
      action: "upsert",
      message_id: 109,
      summary: summary(3),
    });
    await page.getByText("Новое сообщение для автопрокрутки").waitFor({ state: "visible" });
    await page.waitForFunction(() => {
      const history = document.querySelector(".messages");
      return history && history.scrollHeight > history.clientHeight &&
        history.scrollHeight - history.scrollTop - history.clientHeight <= 2;
    });

    // Мобильное «Назад» не должно выбрасывать уже прочитанную историю.
    // Сразу показываем сообщения из короткого кэша, параллельно запрашивая сервер.
    await page.setViewportSize({ width: 390, height: 800 });
    const delayedMessageResponses = [];
    await page.route("**/api/panel/personal-conversations/5/messages", route => {
      delayedMessageResponses.push(route);
    });
    await page.getByRole("button", { name: "Назад к списку диалогов" }).click();
    await page.getByRole("button", { name: /Учитель/ }).click();
    await page.getByText("Новое сообщение для автопрокрутки").waitFor({ state: "visible" });
    await waitFor(() => delayedMessageResponses.length === 1);
    await delayedMessageResponses[0].fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([{
        id: 77,
        sender: "Администратор",
        sender_role: "admin",
        can_delete: false,
        content_type: "text",
        text: "Проверка адресной синхронизации",
        metadata: {},
        delivery_status: "delivered",
        panel_read_at: null,
        created_at: "2026-11-21T10:00:00+00:00",
      }, ...syncNewMessages]),
    });
    await page.getByText("Новое сообщение для автопрокрутки").waitFor({ state: "visible" });

  } finally {
    for (const response of pendingPersonalResponses.splice(0)) {
      response.writeHead(200, { "Content-Type": "application/json" });
      response.end("[]");
    }
    for (const response of [...streams]) response.end();
    await browser?.close();
    vite?.kill("SIGTERM");
    if (apiServer?.listening) await new Promise(resolve => apiServer.close(resolve));
  }
});
