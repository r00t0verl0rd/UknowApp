import assert from "node:assert/strict";
import test from "node:test";
import { chromium } from "playwright";
import { preview } from "vite";

const HOST = "http://127.0.0.1:22239";
const users = Array.from({ length: 90 }, (_, i) => ({
  id: i + 100, role: "student", full_name: `Ученик ${String(i + 1).padStart(3, "0")}`,
  web_username: `student${i + 1}`, telegram_id: null,
}));

test("remembers current page, list filters and scroll after asynchronous reload", { timeout: 85000 }, async () => {
  const server = await preview({
    preview: { host: "127.0.0.1", port: 22239, strictPort: true }, logLevel: "error",
  });
  const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH });
  try {
    for (const viewport of [{ width: 1280, height: 720 }, { width: 390, height: 760 }]) {
      const page = await browser.newPage({ viewport, hasTouch: viewport.width < 500, isMobile: viewport.width < 500 });
      let usersFetches = 0;
      await page.route("**/api/**", async route => {
        const routeName = new URL(route.request().url()).pathname;
        if (routeName === "/api/panel/me") return route.fulfill({
          json: { full_name: "Администратор", role: "admin",
            permissions: ["structure.view", "users.manage", "dialogs.own", "school.manage", "dialogs.observe"] },
        });
        if (routeName === "/api/admin/users") {
          usersFetches++;
          if (usersFetches > 1) await new Promise(done => setTimeout(done, 320));
          return route.fulfill({ json: [...users, { id: 8, role: "teacher", full_name: "Анна" }] });
        }
        if (routeName === "/api/admin/overview") return route.fulfill({
          json: { counts: { teachers: 1, students: users.length }, teachers: [{ id: 8, students: [users[0]] }] },
        });
        if (routeName === "/api/panel/conversations" || routeName === "/api/panel/personal-conversations") {
          return route.fulfill({ json: [] });
        }
        return route.fulfill({ json: [] });
      });

      await page.goto(HOST);
      await page.evaluate(() => localStorage.setItem("uknowapp-auth", "1"));
      await page.goto(HOST + "/users");
      const first = page.getByText("Ученик 001", { exact: true });
      await first.waitFor({ state: "visible" });
      await page.getByLabel("Поиск по имени").fill("Ученик");
      await page.getByLabel("Сортировка пользователей").selectOption("name-desc");
      await page.getByText("Ученик 090", { exact: true }).waitFor();
      const savedPosition = await page.evaluate(() => {
        const container = document.querySelector(".workspace-content");
        if (container.scrollHeight > container.clientHeight + 350) {
          container.scrollTop = 380;
          return { kind: "content", y: container.scrollTop };
        }
        window.scrollTo(0, 380);
        return { kind: "document", y: window.scrollY };
      });
      assert.ok(savedPosition.y > 100, `${viewport.width}px: enough content to scroll`);
      await page.waitForTimeout(140);
      await page.reload();
      await page.getByText("Ученик 090", { exact: true }).waitFor();
      assert.equal(await page.getByLabel("Сортировка пользователей").inputValue(), "name-desc");
      assert.equal(await page.getByLabel("Поиск по имени").inputValue(), "Ученик");
      await page.waitForFunction(
        pos => {
          const container = pos.kind === "content"
            ? document.querySelector(".workspace-content")
            : document.scrollingElement;
          const y = pos.kind === "content" ? container?.scrollTop : window.scrollY;
          if (Math.abs(y - pos.y) <= 8) return true;
          // On mobile a sticky header may move in the layout. Restoring the
          // same visible row is the invariant, not an arbitrary pixel offset.
          const snapshot = JSON.parse(sessionStorage.getItem("uknowapp-view-v1:admin") || "{}");
          const anchor = snapshot.pages?.users?.scroll?.[pos.kind]?.anchor;
          const row = [...(container?.querySelectorAll("[data-view-anchor]") || [])]
            .find(el => el.getAttribute("data-view-anchor") === anchor?.id);
          if (!row) return false;
          return Math.abs(
            row.getBoundingClientRect().top - container.getBoundingClientRect().top - anchor.offset,
          ) <= 8;
        },
        savedPosition,
        { timeout: 12000 },
      );

      // Moving between sections must keep each section's independent position.
      await page.getByRole("button", { name: "Диалоги", exact: true }).click();
      await page.getByRole("button", { name: "Пользователи", exact: true }).click();
      await page.getByText("Ученик 090", { exact: true }).waitFor();
      await page.waitForFunction(
        pos => {
          const container = pos.kind === "content"
            ? document.querySelector(".workspace-content")
            : document.scrollingElement;
          const y = pos.kind === "content" ? container?.scrollTop : window.scrollY;
          if (Math.abs(y - pos.y) <= 8) return true;
          // On mobile a sticky header may move in the layout. Restoring the
          // same visible row is the invariant, not an arbitrary pixel offset.
          const snapshot = JSON.parse(sessionStorage.getItem("uknowapp-view-v1:admin") || "{}");
          const anchor = snapshot.pages?.users?.scroll?.[pos.kind]?.anchor;
          const row = [...(container?.querySelectorAll("[data-view-anchor]") || [])]
            .find(el => el.getAttribute("data-view-anchor") === anchor?.id);
          if (!row) return false;
          return Math.abs(
            row.getBoundingClientRect().top - container.getBoundingClientRect().top - anchor.offset,
          ) <= 8;
        },
        savedPosition,
        { timeout: 12000 },
      );
      await page.getByRole("button", { name: "Структура", exact: true }).click();
      await page.getByRole("button", { name: "Скрыть учеников", exact: true }).click();
      await page.addInitScript(() => sessionStorage.clear());
      await page.reload();
      const showStudents = page.getByRole("button", { name: "Показать учеников", exact: true });
      await showStudents.waitFor();
      assert.equal(await page.locator(".teacher-branch .student-card").count(), 0);
      await showStudents.click();
      await page.reload();
      await page.locator(".teacher-branch .student-card").getByText("Ученик 001", { exact: true }).waitFor();
      await page.close();
    }
  } finally {
    await browser.close();
    await new Promise((resolve, reject) => server.httpServer.close(err => err ? reject(err) : resolve()));
  }
});

test("restores the selected conversation and the same message after loading older history", { timeout: 65000 }, async () => {
  const server = await preview({
    preview: { host: "127.0.0.1", port: 22240, strictPort: true }, logLevel: "error",
  });
  const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH });
  const chat = {
    id: 7, teacher: { id: 8, full_name: "Преподаватель" },
    student: { id: 9, full_name: "Ученик" }, status: "active",
    message_count: 120, unread_count: 0, created_at: "2026-10-01T10:00:00Z",
  };
  const messages = Array.from({ length: 120 }, (_, i) => ({
    id: i + 1, sender_id: 8, sender: "Преподаватель", sender_role: "teacher",
    created_at: new Date(Date.UTC(2026, 9, 1, 10, i)).toISOString(),
    content_type: "text", text: `Chat message ${String(i + 1).padStart(3, "0")}`,
    metadata: {}, can_delete: false, delivery_status: "delivered",
  }));
  for (const i of [72, 119]) {
    messages[i].metadata.media = { kind: "voice", archive_status: "stored", mime_type: "audio/ogg" };
  }
  let role = "admin";
  let savedId;
  let delayNewerPages = false;
  let resumeNewer;
  const newerGate = new Promise(resolve => { resumeNewer = resolve; });
  try {
    const page = await browser.newPage({ viewport: { width: 1280, height: 720 } });
    await page.route("**/api/**", async route => {
      const url = new URL(route.request().url());
      const name = url.pathname;
      if (name === "/api/panel/me") return route.fulfill({ json: {
        ...(role === "admin" ? {} : { id: 9 }), full_name: "Пользователь", role,
        permissions: ["structure.view", "dialogs.own", "users.manage", "dialogs.observe"],
      } });
      if (name === "/api/panel/conversations") return route.fulfill({ json: [chat] });
      if (name === "/api/panel/personal-conversations") {
        if (delayNewerPages) await newerGate;
        return route.fulfill({ json: [] });
      }
      if (name === "/api/panel/conversations/7/messages") {
        const anchor = Number(url.searchParams.get("around_id")) ||
          (url.searchParams.get("first_unread") === "true" ? 60 : 0);
        if (anchor) {
          const earlier = messages.filter(row => row.id < anchor).slice(-50);
          const later = messages.filter(row => row.id >= anchor).slice(0, 50);
          return route.fulfill({ json: { messages: earlier.concat(later), anchor_id: anchor,
            has_older: earlier.length === 50, has_newer: later.length === 50 } });
        }
        const before = Number(url.searchParams.get("before_id")) || Infinity;
        if (url.searchParams.get("forward") === "true") {
          const after = Number(url.searchParams.get("after_id"));
          if (delayNewerPages && after >= savedId) await newerGate;
          return route.fulfill({ json: messages.filter(row => row.id > after).slice(0, 50) });
        }
        return route.fulfill({ json: messages.filter(row => row.id < before).slice(-50) });
      }
      if (name === "/api/admin/overview") return route.fulfill({ json: { teachers: [] } });
      if (name === "/api/admin/users") return route.fulfill({ json: [] });
      return route.fulfill({ json: [] });
    });
    await page.goto("http://127.0.0.1:22240");
    await page.evaluate(() => localStorage.setItem("uknowapp-auth", "1"));
    await page.goto("http://127.0.0.1:22240/dialogs");
    await page.getByRole("button", { name: "Участники", exact: true }).click();
    await page.locator(".chat-item").first().click();
    await page.getByText("Chat message 120").waitFor({ state: "visible" });
    await page.locator('[data-view-anchor="message:120"] audio').waitFor({ state: "attached" });
    assert.equal(await page.locator('[data-view-anchor="message:73"] audio').count(), 0);
    await page.getByRole("button", { name: "Показать предыдущие сообщения" }).click();
    await page.getByText("Chat message 021").waitFor({ state: "visible" });

    const original = await page.locator(".messages").evaluate(element => {
      element.scrollTop = 280;
      return element.scrollTop;
    });
    assert.ok(original > 100, "Scrolled into older messages");
    await page.waitForTimeout(160);
    const anchor = await page.locator(".messages").evaluate(history => {
      const top = history.getBoundingClientRect().top;
      const row = [...history.querySelectorAll("[data-view-anchor]")].find(el => el.getBoundingClientRect().bottom > top);
      return { id: row.dataset.viewAnchor, offset: row.getBoundingClientRect().top - top };
    });
    savedId = Number(anchor.id.split(":")[1]);
    delayNewerPages = true;
    await page.addInitScript(() => {
      function sample() {
        const history = document.querySelector(".messages");
        if (history && getComputedStyle(history).visibility === "visible") {
          const top = history.getBoundingClientRect().top;
          const row = [...history.querySelectorAll("[data-view-anchor]")].find(el => el.getBoundingClientRect().bottom > top);
          if (row) {
            window.firstChatRow = { id: row.dataset.viewAnchor, offset: row.getBoundingClientRect().top - top };
            return;
          }
        }
        requestAnimationFrame(sample);
      }
      requestAnimationFrame(sample);
    });
    await page.reload();
    const checkFirstFrame = async () => {
      await page.waitForFunction(() => window.firstChatRow, null, { timeout: 10000 });
      const first = await page.evaluate(() => window.firstChatRow);
      assert.equal(first.id, anchor.id);
      assert.ok(Math.abs(first.offset - anchor.offset) < 3);
    };
    await checkFirstFrame();
    assert.equal(await page.getByText("Chat message 120").count(), 0);
    delayNewerPages = false;
    resumeNewer();
    await page.getByText("Chat message 120").waitFor({ state: "attached" });
    // Appending the rest of the history must also preserve the observed row.
    await page.waitForFunction(expected => {
      const history = document.querySelector(".messages");
      const row = history?.querySelector(`[data-view-anchor="${expected.id}"]`);
      return row && Math.abs(row.getBoundingClientRect().top - history.getBoundingClientRect().top - expected.offset) < 3;
    }, anchor);
    assert.equal(await page.locator(".chat-item.selected").count(), 1);
    // Closing a tab removes its session state. A manual reopen still finds the same row.
    await page.goto("about:blank");
    await page.addInitScript(() => sessionStorage.clear());
    await page.goto("http://127.0.0.1:22240/dialogs");
    await page.locator(".chat-item").first().click();
    await checkFirstFrame();
    // On a touch-sized viewport, going back to the list must preserve the anchor.
    await page.setViewportSize({ width: 390, height: 760 });
    await page.locator(".messages").evaluate(history => { history.scrollTop = 420; });
    await page.waitForTimeout(200);
    const mobileAnchor = await page.locator(".messages").evaluate(history => {
      const top = history.getBoundingClientRect().top;
      const row = [...history.querySelectorAll("[data-view-anchor]")]
        .find(el => el.getBoundingClientRect().bottom > top);
      return { id: row.dataset.viewAnchor, offset: row.getBoundingClientRect().top - top };
    });
    const expectMobileAnchor = () => page.waitForFunction(expected => {
      const history = document.querySelector(".messages");
      const row = history?.querySelector(`[data-view-anchor="${expected.id}"]`);
      return history && getComputedStyle(history).visibility === "visible" && row &&
        Math.abs(row.getBoundingClientRect().top - history.getBoundingClientRect().top - expected.offset) < 3;
    }, mobileAnchor);
    await page.getByRole("button", { name: "Назад к списку диалогов" }).click();
    await page.locator(".chat-item").first().click();
    await expectMobileAnchor();
    // Simulate an attachment above the visible row gaining height after loading.
    await page.locator(".messages").evaluate((history, expected) => {
      const row = history.querySelector(`[data-view-anchor="${expected.id}"]`);
      const previous = row.previousElementSibling;
      if (!previous?.dataset.viewAnchor) throw new Error("Expected an earlier message");
      previous.style.minHeight = (previous.getBoundingClientRect().height + 180) + "px";
    }, mobileAnchor);
    await expectMobileAnchor();
    await page.getByRole("button", { name: "К последнему сообщению" }).click();
    await page.waitForFunction(() => {
      const history = document.querySelector(".messages");
      return history.scrollHeight - history.scrollTop - history.clientHeight <= 2;
    });
    await page.getByRole("button", { name: "Назад к списку диалогов" }).click();
    await page.locator(".chat-item").first().click();
    await page.waitForFunction(() => {
      const history = document.querySelector(".messages");
      return history && getComputedStyle(history).visibility === "visible" &&
        history.querySelector('[data-view-anchor="message:120"]') &&
        history.scrollHeight - history.scrollTop - history.clientHeight <= 2;
    });
    // A different account opens at its first unread message.
    await page.setViewportSize({ width: 1280, height: 720 });
    role = "student";
    chat.unread_count = 61;
    messages.forEach(row => { row.panel_read_at = row.id < 60 ? row.created_at : null; });
    await page.goto("about:blank");
    await page.goto("http://127.0.0.1:22240/dialogs");
    await page.locator(".chat-item").first().click();
    await page.waitForFunction(() => {
      const history = document.querySelector(".messages");
      const row = history?.querySelector('[data-view-anchor="message:60"]');
      return row && Math.abs(row.getBoundingClientRect().top - history.getBoundingClientRect().top) < 3;
    }, null, { timeout: 5000 });
    await page.close();
  } finally {
    await browser.close();
    await new Promise((resolve, reject) => server.httpServer.close(error => error ? reject(error) : resolve()));
  }
});
