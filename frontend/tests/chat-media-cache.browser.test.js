import assert from "node:assert/strict";
import test from "node:test";
import { chromium } from "playwright";
import { preview } from "vite";

test("warm chats restore the same photo without waiting for network or downloading it again", { timeout: 30000 }, async () => {
  const server = await preview({
    preview: { host: "127.0.0.1", port: 22307, strictPort: true }, logLevel: "error",
  });
  let browser;
  let releaseSync;
  let holdSync = false;
  const gate = new Promise(resolve => { releaseSync = resolve; });
  let mediaRequests = 0;
  let warmSyncRequests = 0;
  const chats = [7, 8].map((id, index) => ({
    id, teacher: { id: 80, full_name: "Преподаватель" },
    student: { id: id + 100, full_name: index ? "Ученик Б" : "Ученик А" },
    status: "active", message_count: 1, unread_count: 0,
    created_at: "2026-10-01T10:00:00Z",
  }));
  const photo = {
    id: 71, sender_id: 80, sender: "Преподаватель", sender_role: "teacher",
    created_at: "2026-10-01T10:00:00Z", content_type: "photo", text: "Фото А",
    metadata: { media: { kind: "photo", archive_status: "stored", mime_type: "image/png", width: 320, height: 240 } },
    can_delete: false, delivery_status: "delivered",
  };
  const other = { ...photo, id: 81, text: "Текст Б", content_type: "text", metadata: {} };
  try {
    browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH });
    const page = await browser.newPage({ viewport: { width: 1280, height: 720 } });
    await page.addInitScript(() => {
      localStorage.setItem("uknowapp-auth", "1");
      window.EventSource = class extends EventTarget { close() {} };
    });
    await page.route("**/api/**", async route => {
      const { pathname } = new URL(route.request().url());
      if (pathname === "/api/panel/me") return route.fulfill({ json: {
        role: "admin", full_name: "Администратор", permissions: ["structure.view", "dialogs.own", "dialogs.observe", "boards.view"],
      } });
      if (pathname === "/api/panel/conversations") return route.fulfill({ json: chats });
      if (pathname === "/api/panel/conversations/7/messages") return route.fulfill({ json: [photo] });
      if (pathname === "/api/panel/conversations/8/messages") return route.fulfill({ json: [other] });
      if (pathname === "/api/panel/messages/71/media") {
        mediaRequests++;
        // Playwright routing disables HTTP caching; node reuse must avoid the GET.
        return route.fulfill({
          contentType: "image/png", headers: { "Cache-Control": "no-store" },
          body: Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jf2sAAAAASUVORK5CYII=", "base64"),
        });
      }
      if (pathname.endsWith("/sync")) {
        const isPhotoChat = pathname.includes("/7/");
        if (isPhotoChat && holdSync) { warmSyncRequests++; await gate; }
        return route.fulfill({ json: { messages: [], updated_messages: [],
          deleted_message_ids: [], has_more: false, summary: chats[isPhotoChat ? 0 : 1] } });
      }
      if (pathname === "/api/admin/overview") return route.fulfill({ json: { teachers: [] } });
      return route.fulfill({ json: [] });
    });
    await page.goto("http://127.0.0.1:22307/dialogs");
    await page.getByRole("button", { name: "Участники", exact: true }).click();
    const chatA = page.locator(".chat-item").filter({ hasText: "Ученик А" });
    const chatB = page.locator(".chat-item").filter({ hasText: "Ученик Б" });
    await chatA.click();
    await page.waitForFunction(() => {
      const img = document.querySelector(".chat-media-image");
      return img?.complete && img.naturalWidth > 0 && getComputedStyle(document.querySelector(".messages")).visibility === "visible";
    });
    await page.evaluate(() => {
      window.firstImage = document.querySelector(".chat-media-image");
      window.firstHeight = window.firstImage.getBoundingClientRect().height;
    });
    assert.equal(mediaRequests, 1);
    await chatB.click();
    await page.getByText("Текст Б", { exact: true }).waitFor({ state: "visible" });
    holdSync = true;
    // Observe the first frame with visible history, not a later settled screenshot.
    await page.evaluate(() => {
      window.warmPaint = new Promise(resolve => {
        const target = [...document.querySelectorAll(".chat-item")].find(el => el.textContent.includes("Ученик А"));
        target.addEventListener("click", () => {
          const start = performance.now();
          const sample = () => {
            const history = document.querySelector(".messages");
            const image = history?.querySelector(".chat-media-image");
            if (!history || getComputedStyle(history).visibility !== "visible" || !history.textContent.includes("Фото А")) {
              requestAnimationFrame(sample);
              return;
            }
            resolve({ ms: performance.now() - start, same: image === window.firstImage,
              loaded: image?.complete && image.naturalWidth > 0,
              height: image?.getBoundingClientRect().height, expected: window.firstHeight });
          };
          requestAnimationFrame(sample);
        }, { capture: true, once: true });
      });
    });
    await chatA.click();
    const paint = await page.evaluate(() => Promise.race([window.warmPaint,
      new Promise((_, reject) => setTimeout(() => reject(new Error("warm dialog waited for the network")), 1000))]));
    assert.equal(paint.same, true, "keep the original DOM image");
    assert.equal(paint.loaded, true, "photo is present at the first visible history frame");
    assert.ok(Math.abs(paint.height - paint.expected) < 1, "photo layout must not jump");
    assert.equal(mediaRequests, 1);
    await page.waitForFunction(() => document.querySelector(".chat-media-image") === window.firstImage);
    // A warm chat still checks server authorization and changes in the background.
    for (let i = 0; i < 50 && !warmSyncRequests; i++) await new Promise(resolve => setTimeout(resolve, 20));
    assert.ok(warmSyncRequests > 0);
    console.log("[warm-chat-first-paint]", Math.round(paint.ms), "ms");
    releaseSync();
    await page.setViewportSize({ width: 390, height: 760 });
    await page.getByRole("button", { name: "Назад к списку диалогов" }).click();
    await chatA.click();
    await page.waitForFunction(() => document.querySelector(".chat-media-image") === window.firstImage &&
      getComputedStyle(document.querySelector(".messages")).visibility === "visible");
    assert.equal(mediaRequests, 1, "mobile reopen must reuse the same image");
  } finally {
    releaseSync();
    await browser?.close();
    await new Promise((resolve, reject) => server.httpServer.close(error => error ? reject(error) : resolve()));
  }
});
