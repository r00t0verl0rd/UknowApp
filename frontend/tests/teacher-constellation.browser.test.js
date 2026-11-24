import assert from "node:assert/strict";
import test from "node:test";
import { chromium } from "playwright";
import { preview } from "vite";

const HOST = "http://127.0.0.1:22257";

test("teacher graph grows around the center without extra lists and highlights islands", { timeout:120000 }, async () => {
  const server = await preview({
    preview:{ host:"127.0.0.1", port:22257, strictPort:true },
    logLevel:"error",
  });
  const browser = await chromium.launch({ executablePath:process.env.CHROMIUM_PATH });
  try {
    for (const [count, width] of [[9, 1280], [42, 1280], [42, 390]]) {
      const page = await browser.newPage({ viewport:{ width, height:900 } });
      await page.addInitScript(() => localStorage.setItem("uknowapp-auth", "1"));
      await page.route("**/api/**", route => {
        const url = new URL(route.request().url());
        if (url.pathname === "/api/panel/me") return route.fulfill({ json:{
          id:7, role:"teacher", full_name:"Профессор",
          permissions:["structure.view", "dialogs.own", "boards.view"],
        } });
        if (url.pathname === "/api/panel/conversations") return route.fulfill({ json:
          Array.from({ length:count }, (_, i) => ({
            id:i + 1, type:"assignment", status:"active",
            student:{ id:i+100, full_name:"Ученик " + String(i + 1).padStart(2, "0") },
            teacher:{ id:7, full_name:"Профессор" },
            unread_count:0,
          })),
        });
        return route.fulfill({ json:[] });
      });
      await page.goto(HOST + "/structure");
      const islands = page.locator(".teacher-zen-student");
      await islands.first().waitFor();
      await page.waitForFunction(expected => document.querySelectorAll(".teacher-zen-student").length === expected, count);
      assert.equal(await islands.count(), count, "all students belong to the constellation");
      assert.equal(await page.getByText("Ещё ученики").count(), 0);
      assert.equal(await page.getByText("МОЙ УЧЕБНЫЙ КРУГ").count(), 0);
      assert.equal(await page.getByText("Вместе к новым знаниям").count(), 0);
      assert.equal(await page.getByText("ВАШ ЦЕНТР").count(), 0);
      assert.equal(await page.getByText(/Преподаватель · .* учен/).count(), 0);

      if (width > 640) {
        const geometry = await islands.evaluateAll(elements => elements.map(el => {
          const r = el.getBoundingClientRect();
          return { x:r.left, y:r.top, width:r.width, height:r.height };
        }));
        for (let i = 0; i < geometry.length; i++) {
          for (let j = i + 1; j < geometry.length; j++) {
            const a = geometry[i], b = geometry[j];
            const intersects = a.x < b.x + b.width - 1 && b.x < a.x + a.width - 1
              && a.y < b.y + b.height - 1 && b.y < a.y + a.height - 1;
            assert.equal(intersects, false, `overlapping islands ${i} and ${j} for ${count} students`);
          }
        }
        const before = await islands.first().evaluate(el => getComputedStyle(el).transform);
        await islands.first().hover();
        await page.waitForTimeout(220);
        const after = await islands.first().evaluate(el => getComputedStyle(el).transform);
        assert.notEqual(after, before, "hover raises and enlarges the student's island");
      } else {
        const stage = page.locator(".teacher-zen-stage");
        assert.equal(await stage.evaluate(el => getComputedStyle(el).overflowX), "visible");
        assert.equal(await islands.last().isVisible(), true);
      }
      await page.close();
    }
  } finally {
    await browser.close();
    await new Promise((resolve, reject) =>
      server.httpServer.close(error => error ? reject(error) : resolve()));
  }
});
