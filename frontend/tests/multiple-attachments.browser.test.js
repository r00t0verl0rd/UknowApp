import assert from "node:assert/strict";
import test from "node:test";
import { chromium } from "playwright";
import { preview } from "vite";

const PORT = 22309;
const HOST = "http://127.0.0.1:" + PORT;
const teacher = { id: 8, role: "teacher", full_name: "Учитель" };
const student = { id: 9, role: "student", full_name: "Ученик" };
const personal = { id: 5, type: "personal", participant: teacher, title: teacher.full_name,
  unread_count: 0, created_at: "2026-11-20T10:00:00Z" };
const participant = { id: 7, type: "conversation", teacher, student, status: "active",
  unread_count: 0, admin_unread_count: 0, message_count: 0, created_at: personal.created_at };

const file = (name, size = 8) => ({ name, mimeType: "text/plain", buffer: Buffer.alloc(size, 65) });
const multipartField = (body, name) => body.match(new RegExp('name="' + name + '"\\r\\n\\r\\n([^\\r\\n]*)'))?.[1];

test("multiple picker and file drops send once, keep unsent files, and retry with stable IDs", { timeout: 60000 }, async () => {
  const server = await preview({ preview: { host: "127.0.0.1", port: PORT, strictPort: true }, logLevel: "error" });
  let browser;
  try {
    browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH });
    for (const chat of [personal, participant]) {
      const context = await browser.newContext({ viewport: { width: 1280, height: 800 } });
      try {
        await context.addInitScript(() => {
          localStorage.setItem("uknowapp-auth", "1");
          window.EventSource = class extends EventTarget { close() {} };
        });
        const page = await context.newPage();
        page.setDefaultTimeout(10000);
        const pageErrors = [];
        page.on("pageerror", error => pageErrors.push(error.message));
        const attempts = [];
        const messages = [];
        let active = 0;
        let peak = 0;
        let failed = false;
        const base = "/api/panel/" + (chat.type === "personal" ? "personal-conversations/" : "conversations/") + chat.id;
        await page.route("**/api/**", async route => {
          const req = route.request();
          const path = new URL(req.url()).pathname;
          let json = [];
          if (path === "/api/panel/me") json = {
            role: "admin", full_name: "Администратор", max_attachment_bytes: 1024,
            permissions: ["dialogs.observe", "dialogs.own", "structure.view", "users.manage"],
          };
          else if (path === "/api/panel/personal-conversations") json = [personal];
          else if (path === "/api/panel/conversations") json = [participant];
          else if (path === "/api/admin/overview") json = { teachers: [] };
          else if (path === base + "/messages") json = messages;
          else if (path === base + "/sync") json = { messages: [], updated_messages: [],
            deleted_message_ids: [], has_more: false, summary: chat };
          else if (path === base + "/attachments") {
            const body = req.postDataBuffer().toString("utf8");
            const name = body.match(/filename="([^"]+)"/)?.[1];
            const id = multipartField(body, "client_message_id");
            const caption = multipartField(body, "text");
            attempts.push({ name, id, caption });
            active++;
            peak = Math.max(peak, active);
            try {
              if (name === "drop-a.txt" && !failed) {
                failed = true;
                return await route.fulfill({ status: 503, json: { detail: "Временная ошибка" } });
              }
              json = { id: messages.length + 100, sender: "Администратор", sender_role: "admin",
                content_type: "text", text: caption || name, created_at: new Date().toISOString(),
                metadata: { client_message_id: id }, delivery_status: "delivered" };
              messages.push(json);
              return await route.fulfill({ status: 201, json });
            } finally { active--; }
          }
          await route.fulfill({ json });
        });
        await page.goto(HOST + "/dialogs");
        if (chat.type === "personal") await page.getByRole("button", { name: "Личные", exact: true }).click();
        await page.locator(".chat-item").first().click();
        const input = page.locator('.chat-composer input[type="file"]');
        const textarea = page.locator(".chat-composer textarea");
        const send = page.getByRole("button", { name: "Отправить сообщение" });
        await textarea.waitFor();
        assert.equal(await input.getAttribute("multiple"), "");
        await input.setInputFiles([file("first.txt"), file("remove.txt")]);
        await page.getByRole("button", { name: "Убрать файл remove.txt" }).click();
        const transfer = await page.evaluateHandle(() => {
          const data = new DataTransfer();
          data.items.add(new File(["a"], "drop-a.txt", { type: "text/plain" }));
          data.items.add(new File(["b"], "drop-b.txt", { type: "text/plain" }));
          return data;
        });
        await textarea.dispatchEvent("dragover", { dataTransfer: transfer });
        await page.locator(".chat-composer.is-file-drag").waitFor();
        await textarea.dispatchEvent("drop", { dataTransfer: transfer });
        await transfer.dispose();
        await page.locator(".chat-composer.is-file-drag").waitFor({ state: "detached" });
        assert.deepEqual(await page.locator(".selected-file-name").allTextContents(),
          ["first.txt", "drop-a.txt", "drop-b.txt"]);
        await textarea.fill("Общая подпись");
        await send.click();
        await page.getByText(/Не удалось отправить «drop-a.txt»/).waitFor();
        await page.getByRole("button", { name: "Закрыть уведомление об ошибке" }).click();
        await page.waitForFunction(() => !document.querySelector(".composer-send").disabled);
        assert.deepEqual(await page.locator(".selected-file-name").allTextContents(), ["drop-a.txt", "drop-b.txt"]);
        assert.equal(await textarea.inputValue(), "");
        await send.click();
        await page.locator(".composer-attachments").waitFor({ state: "detached" });
        assert.deepEqual(attempts.map(item => item.name), ["first.txt", "drop-a.txt", "drop-a.txt", "drop-b.txt"]);
        assert.deepEqual(attempts.map(item => item.caption), ["Общая подпись", "", "", ""]);
        assert.ok(attempts.every(item => item.id));
        assert.equal(attempts[1].id, attempts[2].id);
        assert.equal(new Set(attempts.map(item => item.id)).size, 3);
        assert.equal(peak, 1);
        assert.equal(messages.length, 3);
        assert.equal(await textarea.inputValue(), "");
        await input.setInputFiles([file("oversize.txt", 1025), file("empty.txt", 0), file("valid.txt")]);
        await page.getByText("valid.txt", { exact: true }).waitFor();
        await page.getByText(/Слишком большие файлы: oversize.txt/).waitFor();
        assert.match(await page.locator(".native-feedback-error .toast-message").innerText(), /Пустые файлы: empty.txt/);
        await page.getByRole("button", { name: "Закрыть уведомление об ошибке" }).click();
        assert.deepEqual(await page.locator(".selected-file-name").allTextContents(), ["valid.txt"]);
        await textarea.fill("a".repeat(3901));
        await send.click();
        await page.getByText(/Текст к вложению слишком длинный/).waitFor();
        await page.getByRole("button", { name: "Закрыть уведомление об ошибке" }).click();
        assert.equal(attempts.length, 4, "invalid caption must not start any upload");
        assert.deepEqual(await page.locator(".selected-file-name").allTextContents(), ["valid.txt"]);
        await textarea.fill("");
        await page.getByRole("button", { name: "Убрать файл valid.txt" }).click();
        assert.equal(await send.isDisabled(), true);
        assert.deepEqual(pageErrors, [], "opening a dialog and editing attachments must not throw");
      } finally { await context.close(); }
    }
  } finally {
    await browser?.close();
    await new Promise((resolve, reject) => server.httpServer.close(error => error ? reject(error) : resolve()));
  }
});
