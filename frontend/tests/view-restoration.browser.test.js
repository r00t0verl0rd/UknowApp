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
          json: { id: 1, full_name: "Администратор", role: "admin",
            permissions: ["structure.view", "users.manage", "dialogs.own", "school.manage", "dialogs.observe"] },
        });
        if (routeName === "/api/admin/users") {
          usersFetches++;
          if (usersFetches > 1) await new Promise(done => setTimeout(done, 320));
          return route.fulfill({ json: users });
        }
        if (routeName === "/api/admin/overview") return route.fulfill({
          json: { counts: { teachers: 0, students: users.length }, teachers: [] },
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
          const y = pos.kind === "content"
            ? document.querySelector(".workspace-content")?.scrollTop
            : window.scrollY;
          return Math.abs(y - pos.y) <= 8;
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
          const y = pos.kind === "content"
            ? document.querySelector(".workspace-content")?.scrollTop
            : window.scrollY;
          return Math.abs(y - pos.y) <= 8;
        },
        savedPosition,
        { timeout: 12000 },
      );
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
    id: 7, type: "conversation", teacher: { id: 8, full_name: "Преподаватель" },
    student: { id: 9, full_name: "Ученик" }, status: "active",
    message_count: 120, unread_count: 0, created_at: "2026-10-01T10:00:00Z",
  };
  const messages = Array.from({ length: 120 }, (_, i) => ({
    id: i + 1, sender_id: 8, sender: "Преподаватель", sender_role: "teacher",
    created_at: new Date(Date.UTC(2026, 9, 1, 10, i)).toISOString(),
    content_type: "text", text: `Chat message ${String(i + 1).padStart(3, "0")}`,
    metadata: {}, can_delete: false, delivery_status: "delivered",
  }));
  try {
    const page = await browser.newPage({ viewport: { width: 1280, height: 720 } });
    await page.route("**/api/**", route => {
      const url = new URL(route.request().url());
      const name = url.pathname;
      if (name === "/api/panel/me") return route.fulfill({ json: {
        id: 1, full_name: "Администратор", role: "admin",
        permissions: ["structure.view", "dialogs.own", "users.manage", "dialogs.observe"],
      } });
      if (name === "/api/panel/conversations") return route.fulfill({ json: [chat] });
      if (name === "/api/panel/personal-conversations") return route.fulfill({ json: [] });
      if (name === "/api/panel/conversations/7/messages") {
        const before = Number(url.searchParams.get("before_id")) || Infinity;
        return route.fulfill({ json: messages.filter(row => row.id < before).slice(-50) });
      }
      if (name === "/api/admin/overview") return route.fulfill({ json: { teachers: [] } });
      if (name === "/api/admin/users") return route.fulfill({ json: [] });
      return route.fulfill({ json: [] });
    });
    await page.goto("http://127.0.0.1:22240");
    await page.evaluate(() => localStorage.setItem("uknowapp-auth", "1"));
    await page.goto("http://127.0.0.1:22240/dialogs");
    await page.locator(".chat-item").first().click();
    await page.getByText("Chat message 120").waitFor({ state: "visible" });
    await page.getByRole("button", { name: "Показать предыдущие сообщения" }).click();
    await page.getByText("Chat message 021").waitFor({ state: "visible" });

    const original = await page.locator(".messages").evaluate(element => {
      element.scrollTop = 280;
      return element.scrollTop;
    });
    assert.ok(original > 100, "Scrolled into older messages");
    await page.waitForTimeout(160);
    await page.reload();
    await page.getByText("Chat message 021").waitFor({ state: "visible", timeout: 14000 });
    await page.waitForFunction(expected =>
      Math.abs(document.querySelector(".messages")?.scrollTop - expected) < 14,
    original, { timeout: 14000 });
    assert.equal(await page.locator(".chat-item.selected").count(), 1);
    await page.close();
  } finally {
    await browser.close();
    await new Promise((resolve, reject) => server.httpServer.close(error => error ? reject(error) : resolve()));
  }
});
