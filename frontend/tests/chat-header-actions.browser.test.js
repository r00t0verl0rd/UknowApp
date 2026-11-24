import assert from "node:assert/strict";
import test from "node:test";
import { chromium } from "playwright";
import { preview } from "vite";

const HOST = "http://127.0.0.1:22261";

test("chat header icons are identical across screen widths and Telegram status colors reverse", { timeout:90000 }, async () => {
  const server = await preview({ preview:{host:"127.0.0.1",port:22261,strictPort:true},logLevel:"error" });
  const browser = await chromium.launch({ executablePath:process.env.CHROMIUM_PATH });
  try {
    for (const width of [375, 768, 1366]) {
      for (const theme of ["light", "dark-soft"]) {
        const page = await browser.newPage({ viewport:{width,height:850} });
        await page.goto(HOST);
        await page.evaluate(value => {
          document.documentElement.dataset.theme = value;
          document.body.innerHTML = `
            <div class="workspace-shell">
              <div class="chat-head-tools">
                <label class="chat-message-filter-control ui-chat-head-action" aria-label="Фильтр сообщений">
                  <svg viewBox="0 0 24 24"><path d="M4 7h16M7 12h10M10 17h4"/></svg>
                  <span class="chat-message-filter">
                    <select aria-label="Фильтр сообщений"><option>Все сообщения</option></select>
                  </span>
                </label>
                <button class="icon-btn ui-icon-button ui-icon-button--large ui-chat-head-action"
                  aria-label="Закрыть и удалить личный диалог">
                  <svg viewBox="0 0 24 24"><path d="M3 6h18M9 6V4h6v2M5 6l1 15h12l1-15"/></svg>
                </button>
              </div>
              <div class="message">
                <button class="icon-btn ui-icon-button message-detail-btn" data-delivery-complete="true"
                  aria-label="Доставка без проблем"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/></svg></button>
                <button class="icon-btn ui-icon-button message-detail-btn" data-delivery-complete="false"
                  aria-label="Есть предупреждение"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/></svg></button>
              </div>
            </div>
          `;
        }, theme);
        const actual = await page.evaluate(() => {
          const filter = document.querySelector(".chat-message-filter-control");
          const close = document.querySelector(".chat-head-tools .ui-icon-button");
          const size = el => {
            const r = el.getBoundingClientRect();
            const svg = el.querySelector("svg").getBoundingClientRect();
            return {width:r.width,height:r.height,iconWidth:svg.width,iconHeight:svg.height};
          };
          return {
            filter:size(filter),
            close:size(close),
            closeText:close.textContent.trim(),
            complete:getComputedStyle(document.querySelector('[data-delivery-complete="true"]')).color,
            warning:getComputedStyle(document.querySelector('[data-delivery-complete="false"]')).color,
          };
        });
        assert.deepEqual(actual.filter, {width:40,height:40,iconWidth:18,iconHeight:18},
          `filter dimensions at ${width}px (${theme})`);
        assert.deepEqual(actual.close, actual.filter, `close button matches filter at ${width}px (${theme})`);
        assert.equal(actual.closeText,"", "close button consists of a trash icon only");
        assert.notEqual(actual.complete,actual.warning,
          `complete delivery stays neutral and warning is blue at ${width}px (${theme})`);
        await page.close();
      }
    }
  } finally {
    await browser.close();
    await new Promise((resolve,reject) => server.httpServer.close(err=>err?reject(err):resolve()));
  }
});
