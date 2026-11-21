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
        messages: [],
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

    // Проверяем оформление ролей в обеих темах после CSS-рефакторинга.
    const themeStyles = await page.evaluate(() => {
      const oldTheme = document.documentElement.dataset.theme;
      const wrapper = document.createElement("div");
      wrapper.className = "content";
      wrapper.innerHTML = [
        '<div class="role_node"></div>',
        '<div class="teacher-card"></div>',
        '<div class="student-card"></div>',
      ].join("");
      document.body.append(wrapper);
      const result = {};
      for (const theme of ["light", "dark-soft"]) {
        document.documentElement.dataset.theme = theme;
        result[theme] = {
          body: getComputedStyle(document.body).backgroundColor,
          teacher: getComputedStyle(wrapper.querySelector(".teacher-card")).background,
          student: getComputedStyle(wrapper.querySelector(".student-card")).background,
        };
      }
      wrapper.remove();
      document.documentElement.dataset.theme = oldTheme;
      return result;
    });
    assert.equal(themeStyles["dark-soft"].body, "rgb(23, 27, 37)");
    assert.notEqual(themeStyles.light.teacher, themeStyles["dark-soft"].teacher);
    assert.notEqual(themeStyles.light.student, themeStyles["dark-soft"].student);

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
              <nav>
                <button class="ui-menu-control" type="button">Диалоги</button>
                <button class="ui-menu-control" aria-current="page" type="button">Структура</button>
              </nav>
              <div class="sidebar-bottom">
                <button class="desktop-admin-extra ui-menu-control" type="button">Дополнительно</button>
                <button class="desktop-sidebar-logout ui-menu-control" type="button">Выход</button>
              </div>
            </aside>
            <div class="content">
              <div class="role_node">Администратор</div>
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

    // Проверяем общий квадратный контур кнопок во всех кабинетах, модальных окнах и темах.
    const originalViewport = page.viewportSize();
    for (const width of [390, 1280]) {
      await page.setViewportSize({ width, height: 800 });
      for (const theme of ["light", "dark-soft"]) {
        const styles = await page.evaluate(currentTheme => {
          const previousTheme = document.documentElement.dataset.theme;
          document.documentElement.dataset.theme = currentTheme;
          const sample = document.createElement("div");
          sample.className = "content";
          sample.style.cssText = "position:fixed;top:0;left:0;z-index:-1;visibility:hidden";
          sample.innerHTML = `
            <div class="role_node"></div>
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
    // Стрелка свёрнутого списка смотрит влево, раскрытого — вниз; кнопка цвета ученика.
    for (const theme of ["light", "dark-soft"]) {
      const state = await page.evaluate(selectedTheme => {
        const previous = document.documentElement.dataset.theme;
        document.documentElement.dataset.theme = selectedTheme;
        const host = document.createElement("div");
        host.className = "content";
        host.innerHTML = `
          <div class="role_node"></div>
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
