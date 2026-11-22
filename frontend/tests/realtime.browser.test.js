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
      wrapper.className = "workspace-content";
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
    // Не заменяем React-узлы: добавляем и затем удаляем только тестовый элемент.
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
          const initialTop = sidebar.getBoundingClientRect().top;
          const previousScroll = content.scrollTop;
          const tallSection = document.createElement("div");
          tallSection.style.cssText = "height:2200px;min-height:2200px;flex-shrink:0;";
          try {
            content.append(tallSection);
            content.scrollTop = 500;
            const bg = getComputedStyle(root).getPropertyValue("--workspace-background").trim();
            const canvas = document.createElement("div");
            canvas.style.backgroundColor = bg;
            document.body.append(canvas);
            const resolvedBackground = getComputedStyle(canvas).backgroundColor;
            canvas.remove();
            return {
              scrollTop: content.scrollTop,
              shellPosition: getComputedStyle(shell).position,
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
            root.dataset.theme = previousTheme;
          }
        }, theme);
        assert.equal(isolation.shellPosition, "fixed",
          `${width}px ${theme}: viewport shell is always fixed`);
        assert.ok(isolation.scrollTop >= 400, `${width}px ${theme}: content scrolls independently`);
        assert.equal(isolation.sidebarTop, isolation.initialTop, `${width}px ${theme}: sidebar stays in place`);
        assert.equal(isolation.windowScroll, 0, `${width}px ${theme}: no document scrolling`);
        for (const [label, value] of [
          ["html", isolation.docOverflow], ["body", isolation.bodyOverflow],
          ["root", isolation.rootOverflow],
        ]) {
          assert.equal(value, "hidden",
            `${width}px ${theme}: ${label} never scrolls the document`);
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
        return !!shell && (!vv || Math.abs(shell.getBoundingClientRect().height - vv.height) <= 2);
      });
      const state = await page.evaluate(() => {
        const viewport = window.visualViewport;
        const shell = document.querySelector(".workspace-shell");
        const content = shell.querySelector(".workspace-content");
        const bottom = (viewport?.offsetTop || 0) + (viewport?.height || window.innerHeight);
        const tall = document.createElement("div");
        tall.style.height = "1600px";
        tall.style.flexShrink = "0";
        content.append(tall);
        try {
          content.scrollTop = content.scrollHeight;
          return {
            visibleBottom: bottom,
            shellBottom: shell.getBoundingClientRect().bottom,
            contentBottom: content.getBoundingClientRect().bottom,
            finalItemBottom: tall.getBoundingClientRect().bottom,
            scrollTop: content.scrollTop,
            shellHeight: shell.getBoundingClientRect().height,
            viewportHeight: viewport?.height || window.innerHeight,
          };
        } finally {
          tall.remove();
          content.scrollTop = 0;
        }
      });
      assert.ok(Math.abs(state.shellHeight - state.viewportHeight) <= 2,
        `${width}x${height}: shell follows visualViewport`);
      assert.ok(state.shellBottom <= state.visibleBottom + 2,
        `${width}x${height}: shell does not hide behind browser toolbar`);
      assert.ok(state.contentBottom <= state.visibleBottom + 2,
        `${width}x${height}: section bottom stays visible`);
      assert.ok(state.scrollTop > 100, `${width}x${height}: content can scroll`);
      assert.ok(state.finalItemBottom <= state.visibleBottom + 2,
        `${width}x${height}: the last item remains reachable`);
    }

    // На iPhone sidebar рисует ту же поверхность, что и html,
    // а оболочка не выходит за visualViewport даже с прозрачным Safari chrome.
    await page.setViewportSize({ width: 390, height: 720 });
    await page.waitForFunction(() => {
      const shell = document.querySelector(".workspace-shell");
      const viewport = window.visualViewport;
      return !!shell && (!viewport
        || Math.abs(shell.getBoundingClientRect().height - viewport.height) <= 2);
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
      assert.equal(safeArea.shellHeight, 720, `${theme}: fixed shell matches viewport`);
      assert.equal(safeArea.shellPosition, "fixed", `${theme}: no scrolling the shell`);
      assert.notEqual(safeArea.rootBackground, "rgba(0, 0, 0, 0)");
      assert.equal(safeArea.sidebarBackground, safeArea.rootBackground,
        `${theme}: opaque sidebar matches the shared surface`);
      for (const layer of ["bodyBackground", "mainBackground", "shellBackground"]) {
        assert.equal(safeArea[layer], "rgba(0, 0, 0, 0)",
          `${theme}: only the root paints the workspace background (${layer})`);
      }
    }

    // Safari 26 Liquid Glass: visualViewport может уменьшаться из-за toolbar
    // или клавиатуры; фиксированная оболочка и нижний край контента следуют ему.
    const underlay = await page.evaluate(() => {
      const root = document.documentElement;
      const oldHeight = root.style.getPropertyValue("--workspace-viewport-height");
      root.style.setProperty("--workspace-viewport-height", "570px");
      try {
        const shell = document.querySelector(".workspace-shell");
        const content = shell.querySelector(".workspace-content");
        const row = document.createElement("div");
        row.style.cssText = "height:1400px;flex-shrink:0";
        content.append(row);
        try {
          content.scrollTop = content.scrollHeight;
          return {
            shellPosition: getComputedStyle(shell).position,
            shellHeight: Math.round(shell.getBoundingClientRect().height),
            bottomReserve: parseFloat(getComputedStyle(content).paddingBottom),
            finalItemBottom: row.getBoundingClientRect().bottom,
          };
        } finally {
          row.remove();
          content.scrollTop = 0;
        }
      } finally {
        if (oldHeight) root.style.setProperty("--workspace-viewport-height", oldHeight);
        else root.style.removeProperty("--workspace-viewport-height");
      }
    });
    assert.equal(underlay.shellPosition, "fixed");
    assert.equal(underlay.shellHeight, 570,
      "shell follows visible Safari viewport rather than document height");
    assert.ok(underlay.bottomReserve >= 8,
      "content keeps a comfortable bottom inset");
    assert.ok(underlay.finalItemBottom <= 572,
      "last item can be scrolled above the Safari browser controls");

    // Открытый чат: отдельная прокрутка сообщений, поле отправки внутри
    // уменьшенного visualViewport и под неподвижным sidebar.
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
          shellHeight: Math.round(document.querySelector(".workspace-shell").getBoundingClientRect().height),
          messagesScrollable: detail.querySelector(".messages").scrollHeight > detail.querySelector(".messages").clientHeight,
          sendBottom: detail.querySelector(".composer-send").getBoundingClientRect().bottom,
          composerBottom: detail.querySelector(".chat-composer").getBoundingClientRect().bottom,
        };
      } finally {
        list.remove();
        detail.remove();
        if (before) root.style.setProperty("--workspace-viewport-height", before);
        else root.style.removeProperty("--workspace-viewport-height");
      }
    });
    assert.equal(chatUnderlay.shellHeight, 570);
    assert.ok(chatUnderlay.messagesScrollable,
      "messages scroll within the available chat viewport");
    assert.ok(chatUnderlay.sendBottom <= 572,
      "send button remains above Safari controls");
    assert.ok(chatUnderlay.composerBottom <= 572,
      "composer remains inside visible viewport");

    // Чат: форма и «Отправить» прикреплены к видимому низу, сообщения скроллятся.
    for (const { width, height } of [
      { width: 390, height: 720 }, { width: 390, height: 430 },
      { width: 1280, height: 800 },
    ]) {
      await page.setViewportSize({ width, height });
      await page.waitForFunction(() => {
        const vv = window.visualViewport;
        const shell = document.querySelector(".workspace-shell");
        return !!shell && (!vv || Math.abs(shell.getBoundingClientRect().height - vv.height) <= 2);
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
            <div class="composer-footer"><div class="composer-tools"></div>
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
          };
        } finally {
          detail.remove();
          list.remove();
        }
      });
      assert.ok(state.detailBottom <= state.viewportBottom + 2,
        `${width}x${height}: chat fits inside visible viewport`);
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
            <span class="ui-toolbar-select user-sort-field"><select class="ui-toolbar-control ui-toolbar-select-native user-sort"><option>Сначала ученики</option></select><svg class="ui-toolbar-select-chevron"></svg></span>
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
        assert.deepEqual(result.styles.map(x => x.height), [38, 38, 38, 38],
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
        assert.equal(controls.newWidth, 38);
        assert.equal(controls.newHeight, 38);
        assert.ok(controls.verticalGap <= 1);
        assert.notEqual(controls.selectedBackground, controls.inactiveBackground);
      }
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
                <span class="ui-toolbar-select user-sort-field"><select class="ui-toolbar-control ui-toolbar-select-native user-sort"><option>Сначала ученики</option></select><svg class="ui-toolbar-select-chevron"></svg></span>
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
                <label class="chat-filter"><span class="ui-toolbar-select chat-filter-field"><select class="ui-toolbar-control ui-toolbar-select-native"><option>Все личные</option></select><svg class="ui-toolbar-select-chevron"></svg></span></label>
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
              <span class="ui-toolbar-select user-sort-field"><select class="ui-toolbar-control ui-toolbar-select-native user-sort"><option>Сначала ученики</option></select><svg class="ui-toolbar-select-chevron"></svg></span>
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
                <label class="chat-filter"><span class="ui-toolbar-select chat-filter-field"><select class="ui-toolbar-control ui-toolbar-select-native"><option>Все личные</option></select><svg class="ui-toolbar-select-chevron"></svg></span></label>
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
          assert.equal(controls[name].height, 38, `${width}px ${theme}: ${name} height`);
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

    // Выпадающие списки на обеих вкладках идентичны в Safari и Chromium.
    for (const width of [390, 1280]) {
      await page.setViewportSize({ width, height: 800 });
      for (const theme of ["light", "dark-soft"]) {
        const styles = await page.evaluate(currentTheme => {
          const old = document.documentElement.dataset.theme;
          document.documentElement.dataset.theme = currentTheme;
          const host = document.createElement("div");
          host.innerHTML = `
            <span class="ui-toolbar-select user-sort-field">
              <select class="ui-toolbar-control ui-toolbar-select-native user-sort"><option>Сначала ученики</option></select><svg class="ui-toolbar-select-chevron"></svg>
            </span>
            <span class="ui-toolbar-select chat-filter-field">
              <select class="ui-toolbar-control ui-toolbar-select-native"><option>Все личные</option></select><svg class="ui-toolbar-select-chevron"></svg>
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
                arrowVisible: getComputedStyle(el.nextElementSibling).display !== "none",
              };
            });
          } finally {
            host.remove();
            document.documentElement.dataset.theme = old;
          }
        }, theme);
        assert.deepEqual(styles[0], styles[1], `${width}px ${theme}: одинаковое оформление select`);
        assert.equal(styles[0].height, 38);
        assert.equal(styles[0].radius, "9px");
        assert.equal(styles[0].appearance, "none");
        assert.ok(styles[0].arrowVisible);
      }
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
        host.className = "workspace-content";
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
