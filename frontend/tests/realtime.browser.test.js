Warning: truncated output (original token count: 38029)
Total output lines: 2774

import assert from "node:assert/strict";
import { createServer } from "node:http";
import { spawn } from "node:child_process";
import { setTimeout as delay } from "node:timers/promises";
import test from "node:test";
import { chromium } from "playwright";
import { RESPONSIVE_VIEWPORT_WIDTHS } from "./support/responsive-viewports.js";

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
  const timerStart = performance.now();
  let lastPhase = timerStart;
  const markPhase = name => {
    const now = performance.now();
    console.log(`[browser-phase] ${name}: ${Math.round(now - lastPhase)}ms (total ${Math.round(now - timerStart)}ms)`);
    lastPhase = now;
  };

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
      body = { role: "admin", permissions: ["structure.view", "dialogs.own", "users.manage", "boards.view", "school.manage", "dialogs.observe"], full_name: "Администратор" };
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
        can_delete: true,
        content_type: "text",
        text: "Проверка адресной синхронизации",
        metadata: { messenger_deliveries: {
          telegram: { delivered: [], errors: [{ name: "Учитель", role: "teacher", reason: "Аккаунт получателя не подключён к TELEGRAM" }] },
        } },
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
      "node_modules/vite/bin/vite.js", "preview",
      "--host", "127.0.0.1",
      "--port", String(APP_PORT),
      "--strictPort",
    ], { cwd: process.cwd(), env: { ...process.env, VITE_API_BASE_URL: "" }, stdio: "ignore" });
    await waitFor(async () => {
      const response = await fetch(APP_URL);
      return response.ok;
    });

    markPhase("preview ready");
    browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_PATH });
    markPhase("browser launched");
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
    markPhase("login visuals");
    // Личный кабинет учителя: три вкладки, собственные ученики
    // в «Структуре», возврат к существующему списку диалогов.
    const teacherContext = await browser.newContext();
    try {
      await teacherContext.addInitScript(() => {
        localStorage.setItem("uknowapp-auth", "1");
        // Synthetic SSE events stay inside this teacher tab, not the shared server log.
        const NativeEventSource = window.EventSource;
        window.EventSource = class extends NativeEventSource {
          constructor(...args) {
            super(...args);
            window.__teacherTestStream = this;
          }
        };
      });
      const teacherPage = await teacherContext.newPage();
      await teacherPage.route("**/api/panel/me", route => route.fulfill({
        status: 200, contentType: "application/json",
        body: JSON.stringify({ role: "teacher", permissions: ["structure.view", "dialogs.own", "boards.view"], id: 7, full_name: "Светлана Ивановна" }),
      }));
      const teacherDialog = {
        id: 15,
        type: "assignment",
        status: "active",
        student: { id: 27, full_name: "Тестовый ученик" },
        teacher: { id: 7, full_name: "Светлана Ивановна" },
        unread_count: 0,
        created_at: "2026-11-23T10:00:00+00:00",
      };
      const teacherMessage = {
        id: 11,
        sender: "Светлана Ивановна",
        sender_role: "teacher",
        text: "Открытый диалог учителя",
        content_type: "text",
        metadata: {},
        delivery_status: "delivered",
        panel_read_at: null,
        created_at: "2026-11-23T10:01:00+00:00",
      };
      let teacherSyncRequests = 0;
      let teacherSyncMessages = [];
      await teacherPage.route("**/api/panel/conversations", route => route.fulfill({
        status: 200, contentType: "application/json", body: JSON.stringify([teacherDialog]),
      }));
      await teacherPage.route("**/api/panel/conversations/15/messages*", route => route.fulfill({
        status: 200, contentType: "application/json", body: JSON.stringify([teacherMessage]),
      }));
      await teacherPage.route("**/api/panel/conversations/15/sync", route => {
        teacherSyncRequests += 1;
        return route.fulfill({
          status: 200, contentType: "application/json",
          body: JSON.stringify({
            messages: teacherSyncMessages,
            updated_messages: [],
            deleted_message_ids: [],
            summary: { ...teacherDialog, unread_count: teacherSyncMessages.length ? 1 : 0 },
          }),
        });
      });
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
      await teacherPage.getByRole("button", { name: "Доски", exact: true }).click();
      await teacherPage.getByText("В разработке").waitFor({ state: "visible" });
      await teacherPage.getByRole("button", { name: "Диалоги", exact: true }).click();
      await teacherPage.locator(".chat-list").waitFor({ state: "visible" });
      await teacherPage.getByRole("button", { name: /Тестовый ученик/ }).click();
      await teacherPage.getByText("Открытый диалог учителя").waitFor({ state: "visible" });
      await teacherPage.locator(".chat-composer textarea").fill("Черновик преподавателя");
      await teacherPage.evaluate(() => {
        window.__teacherDialogNodes = [".chat-head", ".messages", ".chat-composer", ".chat-composer textarea"]
          .map(selector => document.querySelector(selector));
      });
      const teacherNodesAreStable = () => teacherPage.evaluate(() =>
        [".chat-head", ".messages", ".chat-composer", ".chat-composer textarea"]
          .every((selector, index) => document.querySelector(selector) === window.__teacherDialogNodes[index]));
      await teacherPage.waitForFunction(() => Boolean(window.__teacherTestStream));
      const syncBeforeReceipt = teacherSyncRequests;
      await teacherPage.evaluate(() => window.__teacherTestStream.dispatchEvent(
        new MessageEvent("update", { data: JSON.stringify({
          event_id: 901,
          conversation_id: 15,
          conversation_type: "conversation",
          action: "read",
          actor_role: "student",
          message_ids: [11],
          read_at: "2026-11-23T10:02:00+00:00",
          summary: { id: 15, unread_count: 0 },
        }) }),
      ));
      await teacherPage.getByLabel("Прочитано в UknowApp").waitFor({ state: "visible" });
      assert.equal(teacherSyncRequests, syncBeforeReceipt, "a read receipt does not refetch teacher messages");
      assert.equal(await teacherNodesAreStable(), true, "read receipt must not remount teacher dialog");
      teacherSyncMessages = [{
        id: 12,
        sender: "Тестовый ученик",
        sender_role: "student",
        text: "Новое сообщение ученика",
        content_type: "text",
        metadata: {},
        delivery_status: "delivered",
        panel_read_at: null,
        created_at: "2026-11-23T10:03:00+00:00",
      }];
      await teacherPage.evaluate(() => window.__teacherTestStream.dispatchEvent(
        new MessageEvent("update", { data: JSON.stringify({
          event_id: 902,
          conversation_id: 15,
          conversation_type: "conversation",
          action: "upsert",
          message_id: 12,
          summary: { id: 15, unread_count: 1, last_message_at: "2026-11-23T10:03:00+00:00" },
        }) }),
      ));
      await teacherPage.getByText("Новое сообщение ученика").waitFor({ state: "visible" });
      assert.ok(teacherSyncRequests > syncBeforeReceipt, "new student message must sync into teacher chat");
      assert.equal(await teacherNodesAreStable(), true, "incoming message must not remount teacher dialog");
      assert.equal(await teacherPage.locator(".chat-composer textarea").inputValue(), "Черновик преподавателя",
        "incoming message must preserve teacher draft");
      await teacherPage.getByRole("button", { name: "Структура", exact: true }).click();
      await teacherPage.getByText("Тестовый ученик").waitFor({ state: "visible" });
    } finally {
      await teacherContext.close();
    }
    markPhase("teacher workspace");
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
    await page.getByText("В разработке").waitFor({ state: "visible" });
    // Layout fixtures below supply their own workspace content.
    await page.addStyleTag({ content: ".boards-placeholder { display: none !important; }" });

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

    // Меню, нижние пункты и действие создания используют единую геометрию.
    for (const width of RESPONSIVE_VIEWPORT_WIDTHS) {
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
            geometry: (() => {
              const aside = fixture.querySelector(".sidebar");
              const nav = [...aside.querySelectorAll("nav > button")];
              const footer = [...aside.querySelectorAll(".sidebar-bottom > button.ui-menu-control")];
              const bounds = element => element.getBoundingClientRect();
              const list = [...nav, ...footer];
              return {
                heights:list.map(x => Math.round(bounds(x).height)),
                widths:list.map(x => Math.round(bounds(x).width)),
                mainGap:bounds(nav[1]).top - bounds(nav[0]).bottom,
                footerGap:bounds(footer[1]).top - bounds(footer[0]).bottom,
                footerMargin:getComputedStyle(footer[1]).marginTop,
                navLeft:bounds(nav[0]).left,
                footerLeft:bounds(footer[0]).left,
                footerBottomInset:bounds(aside).bottom - bounds(footer[1]).bottom,
                sidebarBottomPadding:parseFloat(getComputedStyle(aside).paddingBottom),
              };
            })(),
            roleLayouts: (() => {
              const menu = fixture.querySelector(".sidebar nav");
              const bottom = fixture.querySelector(".sidebar-bottom");
              const extra = bottom.querySelector(".desktop-admin-extra");
              const buttonHtml = label => '<button class="ui-menu-control" type="button">' + label + '</button>';
              const roles = {
                admin: ["Структура", "Диалоги", "Пользователи", "Доски"],
                teacher: ["Структура", "Диалоги", "Доски"],
                student: ["Диалоги", "Доски"],
              };
              return Object.entries(roles).map(([role, pages]) => {
                fixture.className = "workspace-shell workspace-" + role;
                menu.innerHTML = pages.map(buttonHtml).join("");
                extra.style.display = role === "admin" ? "" : "none";
                const navButtons = [...menu.querySelectorAll("button")];
                const logout = bottom.querySelector(".desktop-sidebar-logout");
                const rect = element => element.getBoundingClientRect();
                const headStyle = getComputedStyle(navButtons[0]);
                const logoutStyle = getComputedStyle(logout);
                return {
                  role,
                  navHeights:navButtons.map(x => Math.round(rect(x).height)),
                  navGap:getComputedStyle(menu).gap,
                  footerGap:getComputedStyle(bottom).gap,
                  logoutHeight:Math.round(rect(logout).height),
                  logoutDisplay:logoutStyle.display,
                  itemFont:headStyle.fontFamily,
                  logoutFont:logoutStyle.fontFamily,
                  itemRadius:headStyle.borderTopLeftRadius,
                  logoutRadius:logoutStyle.borderTopLeftRadius,
                  itemColor:headStyle.color,
                  logoutColor:logoutStyle.color,
                  itemBackground:headStyle.backgroundColor,
                  logoutBackground:logoutStyle.backgroundColor,
                  navLeft:rect(navButtons[0]).left,
                  logoutLeft:rect(logout).left,
                  footerBottom:rect(fixture.querySelector(".sidebar")).bottom - rect(logout).bottom,
                  paddingBottom:parseFloat(getComputedStyle(fixture.querySelector(".sidebar")).paddingBottom),
                  navScrollWidth:menu.scrollWidth,
                  navClientWidth:menu.clientWidth,
                };
              });
            })(),
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
        if (width >= 1025) {
          const g = result.geometry;
          assert.ok(g.heights.every(h => h === 42),
            `${width}px ${theme}: все пункты меню высотой 42px (${g.heights})`);
          assert.ok(g.widths.every(w => w === g.widths[0]),
            `${width}px ${theme}: равная ширина всех пунктов меню (${g.widths})`);
          assert.ok(Math.abs(g.mainGap - 6) < 0.5 && Math.abs(g.footerGap - 6) < 0.5,
            `${width}px ${theme}: одинаковые промежутки в верхней и нижней группах`);
          assert.equal(g.footerMargin, "0px",
            `${width}px ${theme}: нет лишнего отступа перед Выходом`);
          assert.ok(Math.abs(g.navLeft - g.footerLeft) < 0.5,
            `${width}px ${theme}: кнопки начинаются на одной вертикали`);
          assert.ok(Math.abs(g.footerBottomInset - g.sidebarBottomPadding) < 1,
            `${width}px ${theme}: нижняя граница меню следует внутреннему отступу боковой панели (${g.footerBottomInset} / ${g.sidebarBottomPadding})`);
        }
        for (const layout of result.roleLayouts) {
          const label = `${layout.role} ${width}px ${theme}`;
          assert.ok(layout.navHeights.every(h => h === 42),
            `${label}: единая высота кнопок навигации`);
          assert.equal(layout.itemFont, layout.logoutFont, `${label}: одинаковая гарнитура`);
          assert.equal(layout.itemRadius, layout.logoutRadius, `${label}: одинаковое скругление`);
          assert.equal(layout.itemColor, layout.logoutColor, `${label}: одинаковый цвет подписей`);
          assert.equal(layout.itemBackground, layout.logoutBackground, `${label}: одинаковый фон`);
          if (width >= 1025) {
            assert.equal(layout.navGap, "6px", `${label}: единый вертикальный шаг меню`);
            assert.equal(layout.footerGap, "6px", `${label}: единый вертикальный шаг подвала`);
            assert.equal(layout.logoutHeight, 42, `${label}: высота кнопки Выход`);
            assert.ok(Math.abs(layout.navLeft - layout.logoutLeft) < 0.5,
              `${label}: навигация и Выход на одной вертикали`);
            assert.ok(Math.abs(layout.footerBottom - layout.paddingBottom) < 1,
              `${label}: одинаковый нижний отступ`);
          } else {
            assert.equal(layout.navGap, "4px", `${label}: одинаковый горизонтальный шаг`);
            assert.equal(layout.logoutDisplay, "none", `${label}: мобильный Выход только в быстрых действиях`);
          }
        }
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
      viewportObserver.observe(ro…20029 tokens truncated…      const ctx = document.createElement("canvas").getContext("2d");
                  ctx.font = s.font;
                  return ctx.measureText(el.options[0].text).width + 3 <=
                    el.clientWidth - parseFloat(s.paddingLeft) - parseFloat(s.paddingRight);
                })(),
              };
            });
          } finally {
            host.remove();
            document.documentElement.dataset.theme = old;
          }
        }, theme);
        const { textFits: firstFits, ...firstStyle } = styles[0];
        const { textFits: secondFits, ...secondStyle } = styles[1];
        assert.deepEqual(firstStyle, secondStyle, `${width}px ${theme}: одинаковое оформление select`);
        assert.equal(styles[0].height, 42);
        assert.equal(styles[0].radius, "9px");
        assert.equal(styles[0].appearance, "none");
        assert.equal(styles[0].arrowVisible, true);
        assert.equal(styles[0].arrowWidth, "7px");
        assert.equal(styles[2].appearance, "none");
        assert.equal(styles[2].arrowVisible, true);
        assert.ok(styles[2].textFits, `${width}px ${theme}: message filter label must not overlap chevron`);
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
          <div class="modal-actions participant-form-actions">
            <button class="btn primary">Сохранить</button>
            <button class="icon-btn ui-icon-button ui-icon-button--danger user-delete">×</button>
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
            refreshOffset: Math.abs(
              refresh.getBoundingClientRect().top + refresh.getBoundingClientRect().height / 2 -
              refresh.parentElement.getBoundingClientRect().top -
              refresh.parentElement.getBoundingClientRect().height / 2
            ),
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
      assert.deepEqual(dialogGeometry.actionHeights, [44, 44],
        `${width}px: save and delete stay compact and equally tall`);
      assert.equal(dialogGeometry.refreshHeight, 36,
        `${width}px: new access code button fits inside its 44px row`);
      assert.ok(dialogGeometry.refreshOffset < 2,
        `${width}px: new access code button is vertically centered`);
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
    // All feedback variants share responsive placement and theme.
    for (const width of [390, 760, 1280]) {
      await page.setViewportSize({ width, height: 800 });
      for (const theme of ["light", "dark-soft"]) {
        for (const kind of ["info", "success", "error"]) {
          const notice = await page.evaluate(([currentTheme, kind]) => {
            const root = document.documentElement;
            const previous = root.dataset.theme;
            root.dataset.theme = currentTheme;
            const dialog = document.createElement("dialog");
            dialog.className = "modal native-dialog native-feedback-dialog native-feedback-" + kind;
            dialog.tabIndex = -1;
            dialog.innerHTML = '<div class="native-feedback-content"><div class="native-feedback-copy"><h2>Уведомления</h2><p class="toast-message">Откройте приложение с экрана «Домой»</p></div></div>';
            document.body.append(dialog);
            try {
              if (kind === "error") dialog.showModal();
              else dialog.show();
              dialog.focus();
              const bounds = dialog.getBoundingClientRect();
              const style = getComputedStyle(dialog);
              return {
                right: bounds.right,
                centerX: bounds.left + bounds.width / 2,
                viewCenterX: window.innerWidth / 2,
                width: bounds.width,
                border: style.borderTopWidth,
                radius: style.borderTopLeftRadius,
                outline: style.outlineStyle,
                background: style.backgroundColor,
                text: dialog.querySelector(".toast-message").textContent,
              };
            } finally {
              dialog.close();
              dialog.remove();
              root.dataset.theme = previous;
            }
          }, [theme, kind]);
          assert.ok(width <= 760 ? Math.abs(notice.centerX - notice.viewCenterX) < 2 : Math.abs(width - notice.right - 18) < 2,
            `${width}px ${theme}: ${kind} placement`);
          assert.ok(notice.width <= width - 24, `${width}px: toast fits screen`);
          assert.equal(notice.border, "1px", `${width}px: toast has subtle border`);
          assert.equal(notice.outline, "none", `${width}px: no native blue focus ring`);
          assert.ok(notice.background !== "rgba(0, 0, 0, 0)");
          assert.match(notice.text, /экрана «Домой»/);
        }
      }
    }
    await page.setViewportSize({ width: 1280, height: 800 });

    // Назначение ученика — обычное действие, включённые уведомления имеют цвет выбора.
    for (const width of [390, 760, 1024, 1280]) {
      await page.setViewportSize({ width, height: 800 });
      for (const theme of ["light", "dark-soft"]) {
        const styles = await page.evaluate(nextTheme => {
          const root = document.documentElement;
          const oldTheme = root.dataset.theme;
          root.dataset.theme = nextTheme;
          const host = document.createElement("div");
          host.className = "workspace-shell";
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
                <button class="btn add-student"><svg aria-hidden="true"></svg>Назначить ученика</button>
              </section></div>
              <form class="chat-composer"><span class="selected-file">
                <span class="selected-file-name">example.pdf</span>
                <button class="ui-icon-button" type="button">×</button>
              </span></form>
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
          const attachmentText = document.createElement("span");
          attachmentText.style.cssText = "color:var(--ui-control-text)";
          host.append(reference, action, attachmentText);
          try {
            return {
              selected: prop(reference),
              action: prop(action),
              add: prop(host.querySelector(".add-student")),
              addHeight: Math.round(host.querySelector(".add-student").getBoundingClientRect().height),
              addFontSize: getComputedStyle(host.querySelector(".add-student")).fontSize,
              attachment: prop(host.querySelector(".selected-file")),
              attachmentRemove: prop(host.querySelector(".selected-file .ui-icon-button")),
              expectedAttachmentText: prop(attachmentText).color,
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
        assert.equal(styles.addHeight, width < 1025 ? 38 : 34,
          `${width}px ${theme}: compact assign button height`);
        assert.equal(styles.addFontSize, "12px",
          `${width}px ${theme}: compact assign button font size`);
        if (theme === "dark-soft") {
          assert.equal(styles.attachment.background, styles.action.background,
            `${width}px dark: attachment chip uses dark control background`);
          assert.equal(styles.attachment.color, styles.expectedAttachmentText,
            `${width}px dark: attachment filename uses theme text`);
          assert.notEqual(styles.attachmentRemove.background, "rgb(242, 239, 246)",
            `${width}px dark: remove file icon is not light-themed`);
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

    markPhase("UI fixtures and layout");
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
    // Проверяем настоящие клики по иконкам и их центровку на двух ширинах.
    for (const width of [1280, 768, 390, 320]) {
      await page.setViewportSize({ width, height: 800 });
      const infoButton = page.getByRole("button", { name: "Подробности внешней доставки" });
      const deleteButton = page.getByRole("button", { name: "Удалить своё сообщение" });
      await infoButton.waitFor({ state: "visible" });
      const positions = await page.locator(".message:has(.message-detail-btn):has(.message-delete-btn)").first().evaluate(row => {
        const info = row.querySelector(".message-detail-btn");
        const remove = row.querySelector(".message-delete-btn");
        const time = row.querySelector(".message-time");
        const bounds = el => {
          const b = el.getBoundingClientRect();
          return { x: b.x, right: b.right, top: b.top, bottom: b.bottom, size: b.width, background: getComputedStyle(el).backgroundColor };
        };
        return { info: bounds(info), remove: bounds(remove), time: bounds(time), bubble: bounds(row) };
      });
      assert.ok(Math.abs(positions.info.x - positions.remove.x) < 1, `${width}px: aligned right column`);
      assert.ok(positions.info.bottom <= positions.remove.top, `${width}px: information above delete`);
      assert.ok(positions.time.right <= positions.info.x, `${width}px: actions clear the timestamp`);
      assert.ok(positions.info.size === 28 && positions.remove.size === 28, `${width}px: compact square icon actions`);
      assert.ok(Math.abs((positions.info.top + positions.info.bottom - positions.time.top - positions.time.bottom) / 2) <= 1);
      assert.equal(positions.info.bottom - positions.info.top, 28);
      assert.equal(positions.remove.top, positions.info.bottom);
      assert.equal(positions.bubble.right - positions.info.right, 4);
      assert.equal(positions.info.background, "rgba(0, 0, 0, 0)");
      assert.equal(positions.remove.background, "rgba(0, 0, 0, 0)");
      await infoButton.click();
      await page.getByRole("dialog", { name: "Подробности внешней доставки" })
        .getByText("Получатель не подключил телеграм-бота.").waitFor({ state: "visible" });
      await page.getByRole("button", { name: "Закрыть подробности доставки" }).click();
      await deleteButton.click();
      await page.getByRole("alertdialog", { name: "Удалить у всех?" }).waitFor({ state: "visible" });
      await page.getByRole("alertdialog", { name: "Удалить у всех?" })
        .getByRole("button", { name: "Отмена" }).click();
    }
    await page.setViewportSize(originalViewport);
    await page.evaluate(() => {
      window.__readReceiptNodes = [".chat-head", ".messages", ".chat-composer"]
        .map(selector => document.querySelector(selector));
    });
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
    assert.equal(await page.evaluate(() =>
      [".chat-head", ".messages", ".chat-composer"]
        .every((selector, index) => document.querySelector(selector) === window.__readReceiptNodes[index])),
    true, "read receipt must keep the active chat DOM intact");
    await delay(150);
    assert.equal(syncRequests, 0, "read receipts should not request a redundant message sync");

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
    assert.ok(syncRequests <= 1, "resuming the dialog may perform one targeted reconciliation");
    // SSE: новое сообщение (даже когда читатель прокрутил историю вверх)
    // должно появиться в зоне видимости без скролла всей страницы.
    await page.getByRole("button", { name: /Учитель/ }).click();
    await page.getByText("Проверка адресной синхронизации").waitFor({ state: "visible" });
    await page.locator(".messages").evaluate(el => {
      el.style.height = "120px";
      el.style.maxHeight = "120px";
      el.style.overflowY = "auto";
    });
    await page.locator(".chat-composer textarea").fill("Черновик остаётся при входящем сообщении");
    await page.evaluate(() => {
      window.__upsertNodes = [".chat-head", ".messages", ".chat-composer", ".chat-composer textarea"]
        .map(selector => document.querySelector(selector));
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
    assert.equal(await page.evaluate(() =>
      [".chat-head", ".messages", ".chat-composer", ".chat-composer textarea"]
        .every((selector, index) => document.querySelector(selector) === window.__upsertNodes[index])),
    true, "an incoming message must preserve the open dialog's DOM");
    assert.equal(await page.locator(".chat-composer textarea").inputValue(),
      "Черновик остаётся при входящем сообщении");
    assert.ok(syncRequests > 0, "incoming messages still request targeted synchronization");
    await page.waitForFunction(() => {
      const history = document.querySelector(".messages");
      return history && history.scrollHeight > history.clientHeight &&
        history.scrollHeight - history.scrollTop - history.clientHeight <= 2;
    });

    // Мобильное «Назад» не должно выбрасывать уже прочитанную историю.
    // Сразу показываем сообщения из короткого кэша, параллельно запрашивая сервер.
    await page.setViewportSize({ width: 390, height: 800 });
    const delayedMessageResponses = [];
    await page.route("**/api/panel/personal-conversations/5/messages*", route => {
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
    markPhase("SSE interactions");

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

test("read receipts and push suppression follow the visible dialog", { timeout: 30000 }, async () => {
  const vite = spawn(process.execPath, [
    "node_modules/vite/bin/vite.js", "preview",
    "--host", "127.0.0.1", "--port", String(APP_PORT), "--strictPort",
  ], { env: { ...process.env, VITE_API_BASE_URL: "" }, stdio: "ignore" });
  let browser;
  try {
    await waitFor(async () => (await fetch(APP_URL)).ok);
    browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_PATH });
    const context = await browser.newContext();
    const page = await context.newPage();
    const history = [];
    const unread = new Set();
    const receipts = [];
    let syncRequests = 0;
    let eventId = 0;
    const summary = () => ({ ...personalChat, unread_count: unread.size });
    const openPath = "/api/panel/personal-conversations/5";
    const publish = () => page.evaluate(({ id, chat }) => {
      window.testEventStream.dispatchEvent(new MessageEvent("update", {
        data: JSON.stringify({
          event_id: id,
          action: "upsert",
          conversation_id: chat.id,
          conversation_type: "personal",
          summary: chat,
        }),
      }));
    }, { id: ++eventId, chat: summary() });
    const addMessage = (id, text) => {
      history.push({
        id, text, sender: personalChat.title, sender_role: "teacher", content_type: "text",
        created_at: new Date(Date.UTC(2026, 10, 21, 10, 0, id)).toISOString(),
        panel_read_at: null, metadata: {},
      });
      unread.add(id);
    };
    const checkPush = () => page.evaluate(async () => {
      const { port1, port2 } = new MessageChannel();
      return await new Promise(resolve => {
        port1.onmessage = event => {
          port1.close();
          port2.close();
          resolve(event.data.active);
        };
        navigator.serviceWorker.dispatchEvent(new MessageEvent("message", {
          data: { type: "UKNOW_CHECK_ACTIVE_CHAT", conversationId: 5, conversationType: "personal" },
          ports: [port2],
        }));
      });
    });
    await page.addInitScript(() => {
      localStorage.setItem("uknowapp-auth", "1");
      window.EventSource = class extends EventTarget {
        constructor() {
          super();
          window.testEventStream = this;
        }
        close() {}
      };
    });
    await page.route("**/api/**", async route => {
      const request = route.request();
      const { pathname, searchParams } = new URL(request.url());
      let json = [];
      if (pathname === "/api/panel/me") {
        json = {
          id: 1, role: "admin", full_name: "Администратор",
          permissions: ["structure.view", "dialogs.own", "dialogs.observe", "boards.view"],
        };
      } else if (pathname === "/api/panel/personal-conversations") {
        json = [summary()];
      } else if (pathname === openPath + "/messages") {
        assert.equal(searchParams.get("mark_read"), "false");
        json = history;
      } else if (pathname === openPath + "/sync") {
        syncRequests++;
        const { after_id, mark_read } = request.postDataJSON();
        assert.equal(mark_read, false);
        json = { messages: history.filter(message => message.id > after_id), summary: summary() };
      } else if (pathname === openPath + "/read") {
        const { message_ids } = request.postDataJSON();
        receipts.push(...message_ids);
        for (const id of message_ids) unread.delete(id);
        json = summary();
      }
      await route.fulfill({ json });
    });

    // Ссылка из уже отправленного push ведёт в нужный диалог даже с корневого URL.
    addMessage(1, "Первое уведомление");
    await page.goto(APP_URL + "/?openConversation=5&type=personal");
    await page.getByText("Первое уведомление", { exact: true }).waitFor();
    await waitFor(() => receipts.includes(1));
    assert.equal(new URL(page.url()).pathname, "/dialogs");
    assert.equal(await checkPush(), true);

    await page.getByRole("button", { name: "Доски", exact: true }).click();
    assert.equal(await checkPush(), false);
    const requestsBeforeLeaving = syncRequests;
    addMessage(2, "Получено в другом разделе");
    await publish();
    // Отправка SSE происходит синхронно в странице, а следующий вызов даёт
    // начавшимся сетевым запросам время дойти до обработчика.
    await delay(150);
    assert.equal(syncRequests, requestsBeforeLeaving);
    assert.deepEqual(receipts, [1]);
    assert.equal(unread.size, 1);

    await page.getByRole("button", { name: "Диалоги", exact: true }).click();
    await page.getByText("Получено в другом разделе", { exact: true }).waitFor();
    await waitFor(() => receipts.includes(2));
    assert.equal(unread.size, 0);
    await page.getByLabel("1 непрочитанных личных сообщений").waitFor({ state: "hidden" });

    // Headless Chromium keeps the page focused under automation.
    await page.evaluate(() => {
      Object.defineProperty(document, "visibilityState", { configurable: true, value: "hidden" });
      document.dispatchEvent(new Event("visibilitychange"));
    });
    assert.equal(await checkPush(), false);
    addMessage(3, "Получено в другой вкладке");
    await publish();
    await page.getByLabel("1 непрочитанных личных сообщений").waitFor({ state: "visible" });
    assert.deepEqual(receipts, [1, 2]);

    await page.evaluate(() => {
      delete document.visibilityState;
      document.dispatchEvent(new Event("visibilitychange"));
    });
    await page.getByText("Получено в другой вкладке", { exact: true }).waitFor();
    await waitFor(() => receipts.includes(3));
    assert.deepEqual(receipts, [1, 2, 3]);
    await page.getByLabel("1 непрочитанных личных сообщений").waitFor({ state: "hidden" });
  } finally {
    await browser?.close();
    vite.kill();
  }
});
