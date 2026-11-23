import assert from "node:assert/strict";
import test from "node:test";
import { chromium } from "playwright";
import { preview } from "vite";

const HOST = "http://127.0.0.1:22252";

test("dialog search and select share a row at every screen size", { timeout: 60000 }, async () => {
  const server = await preview({
    preview: { host: "127.0.0.1", port: 22252, strictPort: true }, logLevel: "error",
  });
  const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH });
  try {
    for (const role of ["admin", "teacher"]) {
      for (const width of [390, 760, 1024, 1025, 1280, 1600]) {
        const page = await browser.newPage({ viewport: { width, height: 820 } });
        await page.route("**/api/**", route => {
          const path = new URL(route.request().url()).pathname;
          if (path === "/api/panel/me") return route.fulfill({ json: {
            role,
            id: role === "teacher" ? 9 : undefined,
            full_name: role === "teacher" ? "Преподаватель" : "Администратор",
            permissions: role === "admin"
              ? ["dialogs.observe", "dialogs.own", "users.manage", "structure.view"]
              : ["dialogs.own", "structure.view"],
          } });
          if (path === "/api/admin/overview") return route.fulfill({ json: { teachers: [] } });
          return route.fulfill({ json: [] });
        });
        await page.goto(HOST);
        await page.evaluate(() => localStorage.setItem("uknowapp-auth", "1"));
        await page.goto(HOST + "/dialogs");
        if (role === "admin") await page.getByRole("button", { name: "Личные", exact: true }).click();
        await page.getByRole("combobox", { name: "Фильтр диалогов" }).waitFor();
        for (const selection of ["all", "unread"]) {
          await page.getByRole("combobox", { name: "Фильтр диалогов" }).selectOption(selection);
          for (const rowWidth of [null, 250, 280, 320]) {
            await page.evaluate(value => {
              document.querySelector(".chat-list-filters").style.width = value ? value + "px" : "";
            }, rowWidth);
          const layout = await page.evaluate(() => {
            const search = document.querySelector(".chat-list-filters > .search");
            const filter = document.querySelector(".chat-list-filters > .chat-filter");
            const input = search.querySelector("input");
            const select = filter.querySelector("select");
            const a = search.getBoundingClientRect(), b = filter.getBoundingClientRect();
            const canvas = document.createElement("canvas"), ctx = canvas.getContext("2d");
            const inputStyle = getComputedStyle(input);
            ctx.font = inputStyle.font;
            const placeholderWidth = ctx.measureText(input.placeholder).width;
            const selectStyle = getComputedStyle(select);
            ctx.font = selectStyle.font;
            const options = [...select.options];
            const optionWidth = Math.max(...options.map(o => ctx.measureText(o.textContent).width));
            const usableSelect = select.clientWidth - parseFloat(selectStyle.paddingLeft)
              - parseFloat(selectStyle.paddingRight);
            const usableInput = input.clientWidth - parseFloat(inputStyle.paddingLeft)
              - parseFloat(inputStyle.paddingRight);
            return {
              a: { x:a.x, y:a.y, width:a.width, height:a.height, right:a.right },
              b: { x:b.x, y:b.y, width:b.width, height:b.height, right:b.right },
              placeholderWidth, optionWidth, usableInput, usableSelect,
              panelRight: document.querySelector(".chat-list").getBoundingClientRect().right,
            };
          });
          assert.ok(Math.abs(layout.a.y - layout.b.y) < 2,
            `${role} ${width}px: search and select must share a row: ${JSON.stringify(layout)}`);
          assert.ok(layout.b.x >= layout.a.right - 1);
          assert.ok(layout.b.right <= layout.panelRight);
          assert.ok(layout.usableInput >= layout.placeholderWidth - 1,
            `${role} ${width}px: search placeholder is clipped: ${JSON.stringify(layout)}`);
          assert.ok(layout.usableSelect >= layout.optionWidth - 1,
            `${role} ${width}px: some filter options are clipped: ${JSON.stringify(layout)}`);
          }
        }
        await page.close();
      }
    }
  } finally {
    await browser.close();
    await new Promise((resolve, reject) =>
      server.httpServer.close(error => error ? reject(error) : resolve()));
  }
});
