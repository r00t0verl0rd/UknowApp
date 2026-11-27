import assert from "node:assert/strict";
import test from "node:test";
import { chromium } from "playwright";
import { preview } from "vite";

const HOST = "http://127.0.0.1:22225";
const RESTORE_ID = "restore-flow-browser-test";

test("backup restore explains the restart, asks before re-login and shows verified result", { timeout: 45000 }, async () => {
  const server = await preview({
    preview: { host: "127.0.0.1", port: 22225, strictPort: true },
    logLevel: "error",
  });
  const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH });
  try {
    const page = await browser.newPage();
    let invalidated = false;
    let accepted = false;
    let statusChecks = 0;
    await page.route("**/api/**", route => {
      const url = new URL(route.request().url());
      const path = url.pathname;
      if (path === "/api/auth/login") {
        invalidated = false;
        return route.fulfill({ status: 200, json: { ok: true } });
      }
      if (path === "/api/panel/me") {
        if (invalidated) return route.fulfill({ status: 401, json: { detail: "Session expired" } });
        return route.fulfill({ json: {
          id: 1, full_name: "Администратор", role: "admin",
          permissions: ["structure.view", "dialogs.own", "users.manage", "boards.view", "school.manage", "dialogs.observe"],
        } });
      }
      if (path === "/api/admin/data/full" && route.request().method() === "POST") {
        accepted = true;
        invalidated = true;
        return route.fulfill({ status: 202, json: {
          ok: true, restore_id: RESTORE_ID, automatic_restart: true, restart_required: true,
        } });
      }
      if (path === "/api/admin/data/restore-status") {
        statusChecks += 1;
        if (invalidated) return route.fulfill({ status: 401, json: { detail: "Please log in again" } });
        return route.fulfill({ json: { restore: accepted
          ? { id: RESTORE_ID, status: "completed" }
          : null } });
      }
      if (path === "/api/admin/data/stats") {
        return route.fulfill({ json: { restore: null, database_bytes: 4096, media_bytes: 0, users: 0, teachers: 0, students: 0 } });
      }
      if (path === "/api/admin/overview") return route.fulfill({ json: { teachers: [] } });
      return route.fulfill({ json: [] });
    });

    await page.goto(HOST);
    await page.evaluate(() => localStorage.setItem("uknowapp-auth", "1"));
    await page.goto(HOST + "/additional");
    await page.locator('input[type="file"][accept=".zip,application/zip"]').setInputFiles({
      name: "example-backup.zip", mimeType: "application/zip",
      buffer: Buffer.from("test fixture, server upload is mocked"),
    });
    await page.getByRole("alertdialog", { name: "Восстановить резервную копию?" })
      .getByRole("button", { name: "Восстановить", exact: true }).click();

    await page.getByRole("progressbar", { name: "Ход восстановления резервной копии" }).waitFor();
    await page.getByRole("alertdialog", { name: "Войдите в UknowApp ещё раз" }).waitFor({ timeout: 12000 });
    assert.equal(accepted, true);
    assert.ok(statusChecks > 0);
    assert.ok(page.url().endsWith("/additional"), "The page must not silently redirect to login");

    await page.getByRole("button", { name: "Завершить сеанс и войти снова" }).click();
    await page.getByText("Сессия завершена после восстановления").waitFor({ timeout: 10000 });
    assert.equal(await page.evaluate(() => localStorage.getItem("uknowapp-auth")), null);
    await page.getByLabel("Логин").fill("new-admin");
    await page.getByLabel("Пароль").fill("restored-password");
    await page.getByRole("button", { name: "Войти" }).click();
    await page.getByRole("alertdialog", { name: "Данные восстановлены" }).waitFor({ timeout: 12000 });
    await page.getByRole("button", { name: "Понятно" }).click();
    assert.equal(await page.getByRole("alertdialog", { name: "Данные восстановлены" }).count(), 0);
  } finally {
    await browser.close();
    await new Promise((resolve, reject) => server.httpServer.close(error => error ? reject(error) : resolve()));
  }
});

test("administration explains statistics HTTP 500 and retries without hiding backup controls", { timeout: 40000 }, async () => {
  const server = await preview({
    preview: { host: "127.0.0.1", port: 22225, strictPort: true },
    logLevel: "error",
  });
  const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH });
  try {
    const page = await browser.newPage();
    let statsRequests = 0;
    let statsGate;
    await page.route("**/api/**", async route => {
      const path = new URL(route.request().url()).pathname;
      if (path === "/api/panel/me") {
        return route.fulfill({ json: {
          id: 1, full_name: "Администратор", role: "admin",
          permissions: ["structure.view", "dialogs.own", "users.manage", "boards.view", "school.manage", "dialogs.observe"],
        } });
      }
      if (path === "/api/admin/data/stats") {
        statsRequests += 1;
        if (statsGate) await statsGate;
        return statsRequests === 1
          ? route.fulfill({ status: 500, json: { detail: "Internal Server Error" } })
          : route.fulfill({ json: {
              restore: null, database_bytes: 8192, media_bytes: 0,
              users: statsRequests === 2 ? 7 : 6, teachers: 3, students: statsRequests === 2 ? 4 : 3, assignments: 0,
              conversations: 0, personal_conversations: 0, messages: 0,
              personal_messages: 0, total_messages: 0, telegram_groups: 0,
              connection_codes: 0, media_files: 0, media_images: 0,
              media_audio: 0, media_videos: 0, media_other: 0,
            } });
      }
      if (path === "/api/admin/overview") return route.fulfill({ json: { teachers: [] } });
      return route.fulfill({ json: [] });
    });
    await page.goto(HOST);
    await page.evaluate(() => localStorage.setItem("uknowapp-auth", "1"));
    await page.goto(HOST + "/additional");
    await page.getByText("Не удалось загрузить статистику").waitFor({ timeout: 12000 });
    await page.getByText("Данные остались без изменений. Попробуйте обновить сведения.").waitFor();
    await page.getByText("Технические подробности").click();
    await page.getByText("Сервер не смог получить статистику (HTTP 500)", { exact: false }).waitFor();
    assert.ok(await page.getByRole("heading", { name: "Полная копия ZIP" }).isVisible(),
      "Backup controls remain available when statistics fails");
    assert.equal(await page.getByText("Часть настроек приложения нужно сохранить отдельно.").count(), 0,
      "Obsolete backup settings warning is not displayed");

    await page.getByRole("button", { name: "Повторить загрузку" }).click();
    await page.getByText("7 пользователей").waitFor({ timeout: 12000 });
    assert.ok(statsRequests >= 2);
    assert.equal(await page.getByText("Не удалось загрузить статистику").count(), 0);
    const refresh = page.getByRole("button", { name: "Обновить", exact: true });
    const status = page.locator(".data-stats-loading > span");
    const headerGeometry = () => page.locator(".additional-panel").evaluate(panel => {
      const top = panel.getBoundingClientRect().top;
      const button = panel.querySelector(".data-refresh > button").getBoundingClientRect();
      return {
        statsTop: panel.querySelector(".data-stats-grid").getBoundingClientRect().top - top,
        buttonTop: button.top - top,
        buttonWidth: button.width,
        buttonLeft: button.left,
      };
    });
    for (const width of [1280, 390, 320]) {
      await page.setViewportSize({ width, height: 850 });
      const before = await headerGeometry();
      let release;
      statsGate = new Promise(resolve => { release = resolve; });
      try {
        await refresh.click();
        await status.waitFor({ state: "visible" });
        assert.equal(await refresh.getAttribute("aria-busy"), "true");
        assert.ok(await refresh.isDisabled());
        assert.equal(await refresh.locator("svg").evaluate(svg => getComputedStyle(svg).animationName), "data-refresh-spin");
        const loading = await status.boundingBox();
        const button = await refresh.boundingBox();
        assert.ok(loading.x + loading.width <= button.x + 1, `${width}px: loading status is left of refresh`);
        assert.deepEqual(await headerGeometry(), before, `${width}px: refresh does not shift layout`);
      } finally {
        release();
        statsGate = null;
      }
      await status.waitFor({ state: "hidden" });
      assert.deepEqual(await headerGeometry(), before);
      assert.equal(await refresh.locator("svg").evaluate(svg => getComputedStyle(svg).animationName), "none");
    }
    await page.getByText("6 пользователей", { exact: false }).waitFor();
    assert.equal(statsRequests, 5);
    const databaseCard = page.locator(".data-stat-card").first();
    assert.match(await databaseCard.locator(".data-stat-value").innerText(), /^8\s*КБ$/);
    assert.equal(await databaseCard.getByText("Свободно внутри базы", { exact: false }).count(), 0);
    assert.equal(await databaseCard.getByText("Занято страницами базы", { exact: false }).count(), 0);
    // Одинаковые действия и единый стиль для компьютера и телефона.
    for (const width of [1280, 1024, 900, 760, 390, 320]) {
      await page.setViewportSize({ width, height: 850 });
      const panel = page.locator(".additional-panel");
      await panel.waitFor({ state: "visible" });
      assert.ok(await panel.getByRole("heading", { name: "Полная копия ZIP" }).isVisible());
      const cards = panel.locator(".data-tool-card");
      assert.equal(await cards.count(), 4);
      const geometry = () => cards.evaluateAll(items => items.map(card => {
        const { x, y, width, height } = card.getBoundingClientRect();
        const grid = card.parentElement.getBoundingClientRect();
        return { x: x - grid.x, y: y - grid.y, width, height };
      }));
      const before = await geometry();
      if (width > 760) {
        assert.ok(Math.abs(before[0].y - before[1].y) <= 1 &&
          Math.abs(before[2].y - before[3].y) <= 1 &&
          Math.abs(before[0].x - before[2].x) <= 1 &&
          Math.abs(before[1].x - before[3].x) <= 1 &&
          Math.abs(before[0].height - before[1].height) <= 1 &&
          Math.abs(before[2].height - before[3].height) <= 1,
          `${width}px: four cards align in two columns`);
      } else {
        assert.ok(before.every((card, index) => card.x === before[0].x &&
          (index === 0 || card.y > before[index - 1].y)),
          `${width}px: cards stack in one column`);
      }
      for (const [name, content] of [
        ["О полной копии", "Файл .env и настройки Telegram и MAX сохраняйте отдельно."],
        ["О копии базы данных", "Поддерживаются .db, .sqlite и .sqlite3."],
        ["Об архиве вложений", "Отдельное восстановление этого ZIP через панель не поддерживается."],
        ["Об очистке сообщений", "Пользователи, назначения и диалоги сохраняются."],
      ]) {
        const trigger = panel.getByRole("button", { name, exact: true });
        const popover = panel.getByRole("dialog", { name, exact: true });
        await trigger.click();
        await popover.waitFor({ state: "visible" });
        assert.ok(await popover.getByText(content, { exact: false }).isVisible());
        assert.deepEqual(await geometry(), before, `${width}px: popovers do not stretch cards`);
        if (name === "О полной копии") await page.keyboard.press("Escape");
        else await popover.getByRole("button", { name: "Закрыть подсказку" }).click();
        await popover.waitFor({ state: "hidden" });
      }
      for (const summary of await panel.locator(".data-stat-card > summary").all()) {
        await summary.click();
        assert.deepEqual(await geometry(), before, `${width}px: expanding statistics does not resize cards`);
        await summary.click();
      }
      const mediaAction = await panel.getByRole("button", { name: "Скачать вложения", exact: true }).evaluate(button => {
        const action = button.getBoundingClientRect();
        const group = button.parentElement.getBoundingClientRect();
        return Math.abs(action.left - group.left) <= 1 && Math.abs(action.right - group.right) <= 1;
      });
      assert.ok(mediaAction, `${width}px: the sole attachment action fills the action grid`);
      const buttons = await panel.locator(".data-tool-actions .data-action-btn").evaluateAll(items =>
        items.map(button => ({
          height: button.getBoundingClientRect().height,
          fits: button.scrollWidth <= button.clientWidth + 1,
          nowrap: getComputedStyle(button).whiteSpace === "nowrap",
        })));
      assert.ok(buttons.every(button => Math.abs(button.height - 44) <= 1 && button.fits && button.nowrap),
        `${width}px: backup actions have equal height and fit without wrapping`);
      const cleanupGeometry = await page.locator(".data-cleanup-card").evaluate(card => {
        const action = card.querySelector(".data-cleanup-actions .data-action-btn");
        const retention = card.querySelector(".data-retention-select");
        const button = action.getBoundingClientRect();
        const picker = retention.getBoundingClientRect();
        return {
          height: card.getBoundingClientRect().height,
          buttonHeight: button.height,
          buttonWidth: button.width,
          pickerHeight: picker.height,
          buttonTextNoWrap: getComputedStyle(action).whiteSpace === "nowrap",
          controlGap: Math.abs(button.bottom - picker.bottom),
        };
      });
      assert.ok(cleanupGeometry.height < (width >= 760 ? 260 : 340),
        `${width}px: cleanup card stays compact without empty vertical space`);
      assert.ok(cleanupGeometry.buttonTextNoWrap && cleanupGeometry.buttonWidth >= 110,
        `${width}px: cleanup button text stays on one line`);
      assert.ok(cleanupGeometry.buttonHeight >= 44 && cleanupGeometry.pickerHeight >= 44,
        `${width}px: both controls are convenient to tap`);
      if (width > 760 && cleanupGeometry.buttonWidth >= 150) assert.ok(cleanupGeometry.controlGap <= 52,
        `${width}px: button and retention field align along the bottom`);
      const picker = page.getByLabel("Удалить старше");
      await picker.selectOption("60");
      assert.equal(await picker.inputValue(), "60");
      const selectRect = await picker.evaluate(el => {
        const rect = el.getBoundingClientRect();
        return { height: rect.height, width: rect.width };
      });
      assert.ok(selectRect.height >= 44 && selectRect.width >= 100,
        `${width}px: retention selection is a usable touch target`);
      await page.getByRole("button", { name: "Очистить данные" }).click();
      await page.getByRole("alertdialog", { name: "Удалить старые данные?" })
        .getByText("Сообщения и вложения старше 60 дней", { exact: false }).waitFor();
      await page.getByRole("alertdialog", { name: "Удалить старые данные?" })
        .getByRole("button", { name: "Отмена" }).click();
    }
  } finally {
    await browser.close();
    await new Promise((resolve, reject) => server.httpServer.close(error => error ? reject(error) : resolve()));
  }
});
