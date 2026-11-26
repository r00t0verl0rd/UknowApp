import assert from "node:assert/strict";
import { createServer } from "node:http";
import { spawn } from "node:child_process";
import { setTimeout as delay } from "node:timers/promises";
import test from "node:test";
import { chromium } from "playwright";
import { checkWorkspaceLayout } from "./support/workspace-layout.js";

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

function historyResponse(rows, params, unreadIds = new Set()) {
  const limit = Number(params.get("limit")) || 50;
  const around = Number(params.get("around_id")) ||
    (params.get("first_unread") === "true"
      ? rows.find(row => unreadIds.has(row.id))?.id : null);
  if (around) {
    const before = rows.filter(row => row.id < around).slice(-limit);
    const following = rows.filter(row => row.id >= around).slice(0, limit);
    return { messages: before.concat(following), anchor_id: around,
      has_older: before.length === limit, has_newer: following.length === limit };
  }
  const page = params.get("forward") === "true"
    ? rows.filter(row => row.id > Number(params.get("after_id"))).slice(0, limit)
    : rows.filter(row => row.id < (Number(params.get("before_id")) || Infinity)).slice(-limit);
  return params.get("first_unread") === "true"
    ? { messages: page, anchor_id: null, has_older: page.length === limit, has_newer: false }
    : page;
}

function waitFor(check, timeout = 12000, description = "browser integration condition") {
  const started = Date.now();
  return new Promise((resolve, reject) => {
    const poll = async () => {
      try {
        if (await check()) return resolve();
      } catch { /* Ожидаем готовности браузера или сервера. */ }
      if (Date.now() - started > timeout) return reject(new Error(`Timed out waiting for ${description}`));
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
    const { pathname: path, searchParams } = new URL(request.url, "http://localhost");
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
      if (personalRequests === 1) {
        pendingPersonalResponses.push(response);
        return;
      }
      body = [{ ...personalChat, unread_count: latestUnread }];
    } else if (path === "/api/admin/users") {
      body = [];
    } else if (path === "/api/admin/overview") {
      body = { teachers: [] };
    } else if (path === "/api/admin/boards/objects") {
      body = [];
    } else if (path === "/api/panel/personal-conversations/5/messages") {
      body = historyResponse([{
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
      }, ...syncNewMessages], searchParams, new Set(syncNewMessages.map(row => row.id)));
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
    const originalViewport = page.viewportSize();

    await checkWorkspaceLayout(page, browser, APP_URL);
    markPhase("UI fixtures and layout");
    await waitFor(() => pendingPersonalResponses.length === 1, 12000, "initial pending personal inbox response");
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

        await waitFor(() => streams.size === 1 && inboxRequests > 0 && personalRequests > 0, 12000, "initial SSE connection and inbox requests");
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
      assert.ok(positions.info.size >= 24 && positions.remove.size >= 24, `${width}px: usable icon actions`);
      assert.ok(Math.abs((positions.info.top + positions.info.bottom - positions.time.top - positions.time.bottom) / 2) <= 1);
      assert.ok(positions.remove.top >= positions.info.bottom - 1, "icon actions do not overlap");
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
    await waitFor(() => streams.size === 1, 12000, "single SSE connection before disconnect");
    for (const response of [...streams]) response.end();
    await waitFor(() => streams.size === 0, 12000, "SSE connection closed");
    publish({
      event_id: 103,
      conversation_id: 5,
      conversation_type: "personal",
      action: "upsert",
      summary: summary(2),
    });

    await waitFor(() => lastEventIds.includes(102), 10000, "SSE replay cursor 102");
    await waitFor(() => streams.size === 1, 10000, "SSE reconnection");
    assert.equal(maxActiveStreams, 1, "reconnect must not create parallel SSE connections");

    await page.getByRole("button", { name: "Диалоги" }).click();
    await page.getByRole("button", { name: /Личные/ }).click();
    await page.getByLabel("2 непрочитанных личных сообщений").waitFor({ state: "visible" });
    await waitFor(() => inboxRequests >= 2 && personalRequests >= 2, 10000, "reconciliation after SSE disconnect");
    assert.equal(inboxRequests, 2, "SSE reconnect reconciles the inbox once");
    assert.equal(personalRequests, 2, "SSE reconnect reconciles personal chats once");
    assert.ok(syncRequests <= 1, `resuming the dialog may perform one targeted reconciliation (actual: ${syncRequests})`);
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
    const delayedSyncResponses = [];
    await page.route("**/api/panel/personal-conversations/5/sync", route => {
      delayedSyncResponses.push(route);
    });
    await page.getByRole("button", { name: "Назад к списку диалогов" }).click();
    await page.getByRole("button", { name: /Учитель/ }).click();
    await page.getByText("Новое сообщение для автопрокрутки").waitFor({ state: "visible" });
    await waitFor(() => delayedSyncResponses.length >= 1, 12000, "cached dialog reconciliation POST /sync");
    assert.equal(delayedSyncResponses.length, 1, "one reconciliation for reopening a cached dialog");
    const reconciliation = delayedSyncResponses[0];
    assert.equal(reconciliation.request().method(), "POST");
    const known = reconciliation.request().postDataJSON();
    assert.ok(known.known_message_ids.includes(109), "cached latest message is reconciled with the server");
    await reconciliation.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        messages: [],
        updated_messages: [],
        deleted_message_ids: [],
        has_more: false,
        summary: { ...personalChat, unread_count: latestUnread },
      }),
    });
    await page.getByText("Новое сообщение для автопрокрутки").waitFor({ state: "visible" });
    await page.unroute("**/api/panel/personal-conversations/5/sync");
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
        json = historyResponse(history, searchParams, unread);
      } else if (pathname === openPath + "/sync") {
        syncRequests++;
        const { after_id, mark_read } = request.postDataJSON();
        assert.equal(mark_read, false);
        json = { messages: history.filter(message => message.id > after_id), updated_messages: [],
          deleted_message_ids: [], has_more: false, summary: summary() };
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
    await page.getByText("Получено в другой вкладке", { exact: true }).waitFor();
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
