import assert from "node:assert/strict";
import test from "node:test";
import { chromium } from "playwright";
import { preview } from "vite";

const HOST = "http://127.0.0.1:22248";
const participant = { id: 9, role: "teacher", full_name: "Светлана Иванова" };
const chat = { id: 51, type: "personal", participant, title: participant.full_name,
  created_at: "2026-11-20T12:00:00Z", unread_count: 0 };
const messages = [{ id: 100, sender: "Администратор", sender_role: "admin",
  text: "Личная история", content_type: "text", can_delete: true,
  metadata: {}, created_at: "2026-11-20T13:00:00Z" }];

test("admin confirms before deleting personal conversation; participant cannot delete", { timeout: 60000 }, async () => {
  const server = await preview({ preview: { host: "127.0.0.1", port: 22248, strictPort: true }, logLevel: "error" });
  const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH });
  let removed = false;
  let deletes = 0;

  const openAs = async role => {
    const context = await browser.newContext({ viewport: { width: 1180, height: 800 } });
    await context.addInitScript(() => localStorage.setItem("uknowapp-auth", "1"));
    const page = await context.newPage();
    await page.route("**/api/**", route => {
      const path = new URL(route.request().url()).pathname;
      if (path === "/api/panel/me") return route.fulfill({ json: role === "admin"
        ? { role, full_name: "Администратор", permissions: ["dialogs.observe", "dialogs.own", "users.manage", "structure.view"] }
        : { role, id: participant.id, full_name: participant.full_name, permissions: ["dialogs.own", "structure.view"] },
      });
      if (path === "/api/panel/personal-conversations") return route.fulfill({ json: removed ? [] :
        [role === "admin" ? chat : { ...chat, title: "Администратор" }] });
      if (path === "/api/panel/conversations" || path === "/api/admin/users") return route.fulfill({ json: [] });
      if (path === "/api/admin/overview") return route.fulfill({ json: { teachers: [] } });
      if (path === "/api/panel/personal-conversations/51/messages") return route.fulfill({ json: removed ? [] : messages });
      if (path === "/api/panel/personal-conversations/51/sync") return route.fulfill({ json: {
        messages: [], deleted_message_ids: [], updated_messages: [],
        summary: { ...chat, title: role === "admin" ? chat.title : "Администратор" },
      } });
      if (path === "/api/panel/personal-conversations/51" && route.request().method() === "DELETE") {
        deletes++;
        removed = true;
        return route.fulfill({ json: { ok: true, deleted_conversation_id: 51, deleted_messages: 1 } });
      }
      return route.fulfill({ json: [] });
    });
    await page.goto(HOST + "/dialogs");
    if (role === "admin") await page.getByRole("button", { name: "Личные", exact: true }).click();
    await page.locator(".chat-item").first().click();
    await page.getByText("Личная история").waitFor({ state: "visible" });
    return { context, page };
  };

  try {
    const teacher = await openAs("teacher");
    try {
      assert.equal(await teacher.page.getByRole("button", { name: "Закрыть и удалить личный диалог" }).count(), 0);
      const admin = await openAs("admin");
      try {
        const action = admin.page.getByRole("button", { name: "Закрыть и удалить личный диалог" });
        await action.click();
        const confirm = admin.page.getByRole("alertdialog", { name: "Удалить личный диалог навсегда?" });
        await confirm.waitFor({ state: "visible" });
        assert.match(await confirm.innerText(), /безвозвратно удалены/);
        assert.equal(deletes, 0);
        await confirm.getByRole("button", { name: "Отмена" }).click();
        await confirm.waitFor({ state: "detached" });
        assert.equal(deletes, 0);
        assert.equal(await admin.page.locator(".chat-item").count(), 1);
        await action.click();
        await confirm.getByRole("button", { name: "Удалить диалог" }).click();
        await admin.page.getByText("Личных диалогов пока нет").waitFor({ state: "visible" });
        assert.equal(deletes, 1);
        assert.equal(await admin.page.locator(".chat-item").count(), 0);
      } finally {
        await admin.context.close();
      }
    } finally {
      await teacher.context.close();
    }
  } finally {
    await browser.close();
    await new Promise((resolve, reject) => server.httpServer.close(error => error ? reject(error) : resolve()));
  }
});
