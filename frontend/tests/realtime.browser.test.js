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
      } catch { /* Keep waiting for the browser or server to become ready. */ }
      if (Date.now() - started > timeout) return reject(new Error("Timed out waiting for browser integration condition"));
      setTimeout(poll, 40);
    };
    void poll();
  });
}

test("global SSE updates real counters across tabs and replays missed events", { timeout: 60000 }, async () => {
  const streams = new Set();
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
      body = [personalChat];
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
    ], { cwd: process.cwd(), stdio: "ignore" });
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
    for (const response of [...streams]) response.end();
    await browser?.close();
    vite?.kill("SIGTERM");
    if (apiServer?.listening) await new Promise(resolve => apiServer.close(resolve));
  }
});
