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
    await page.route("**/api/**", route => {
      const path = new URL(route.request().url()).pathname;
      if (path === "/api/panel/me") {
        return route.fulfill({ json: {
          id: 1, full_name: "Администратор", role: "admin",
          permissions: ["structure.view", "dialogs.own", "users.manage", "boards.view", "school.manage", "dialogs.observe"],
        } });
      }
      if (path === "/api/admin/data/stats") {
        statsRequests += 1;
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
    await page.getByRole("button", { name: "Обновить", exact: true }).click();
    await page.getByText("6 пользователей", { exact: false }).waitFor();
    assert.equal(statsRequests, 3);
    const databaseCard = page.locator(".data-stat-card").first();
    assert.match(await databaseCard.locator(".data-stat-value").innerText(), /^8\s*КБ$/);
    assert.equal(await databaseCard.getByText("Свободно внутри базы", { exact: false }).count(), 0);
    assert.equal(await databaseCard.getByText("Занято страницами базы", { exact: false }).count(), 0);
    // Одинаковые действия и единый стиль для компьютера и телефона.
    for (const width of [1280, 1024, 900, 760, 390, 320]) {
      await page.setViewportSize({ width, height: 850 });
      // Compare resting styles rather than a hovered button after viewport changes.
      await page.mouse.move(0, 0);
      await page.waitForTimeout(200);
      const panel = page.locator(".additional-panel");
      await panel.waitFor({ state: "visible" });
      assert.ok(await panel.getByRole("heading", { name: "Полная копия ZIP" }).isVisible());
      const backupSection = panel.getByRole("region", { name: "Резервные копии" });
      assert.equal(await backupSection.locator(".data-tool-card").count(), 3);
      const cards = await backupSection.locator(".data-tool-card").evaluateAll(items => items.map(card => {
        const rect = card.getBoundingClientRect();
        return { left: rect.left, top: rect.top, right: rect.right, bottom: rect.bottom,
          border: getComputedStyle(card).borderTopWidth };
      }));
      assert.ok(cards.every(card => parseFloat(card.border) > 0),
        `${width}px: each backup has a separate card`);
      assert.ok(cards.every(card => card.bottom - card.top < 200),
        `${width}px: backup cards remain compact`);
      const columns = await backupSection.locator(".data-backup-cards").evaluate(grid =>
        getComputedStyle(grid).gridTemplateColumns.split(" ").length);
      if (columns === 3) {
        assert.ok(cards[0].right < cards[1].left && cards[1].right < cards[2].left &&
          Math.abs(cards[0].top - cards[2].top) < 1, "three cards share one row");
        assert.ok(cards.every(card => Math.abs(card.bottom - cards[0].bottom) < 1),
          "desktop: all three cards have aligned lower edges");
        const downloadPositions = await backupSection.locator(".data-tool-card button.data-action-btn").evaluateAll(
          buttons => buttons.map(button => button.getBoundingClientRect().top));
        assert.ok(downloadPositions.every(top => Math.abs(top - downloadPositions[0]) < 1),
          "desktop: all download buttons share one baseline");
      }
      if (width <= 540) {
        assert.ok(cards[0].bottom < cards[1].top && cards[1].bottom < cards[2].top,
          `${width}px: cards stack on mobile`);
      }
      assert.ok(await backupSection.getByText("Восстановление из полной копии", { exact: true }).isVisible(),
        `${width}px: attachment restore method is explained without an extra button`);
      const instructions = backupSection.getByText("Перед восстановлением", { exact: true });
      const before = await backupSection.locator(".data-backup-cards").evaluate(grid => grid.getBoundingClientRect().height);
      await instructions.click();
      const after = await backupSection.locator(".data-backup-cards").evaluate(grid => grid.getBoundingClientRect().height);
      assert.equal(after, before, `${width}px: instructions do not stretch backup cards`);
      await instructions.click();
      await page.mouse.move(0, 0);
      await page.waitForTimeout(200);
      for (const name of ["Скачать полную копию", "Скачать базу", "Скачать вложения"]) {
        const action = backupSection.getByRole("button", { name, exact: true });
        assert.ok(await action.isVisible(), `${width}px: ${name} is visible`);
      }
      const backupGeometry = await backupSection.evaluate(section => {
        const bounds = section.getBoundingClientRect();
        return [...section.querySelectorAll(".data-action-btn")].map(action => {
          const rect = action.getBoundingClientRect();
          const style = getComputedStyle(action);
          const range = document.createRange();
          const label = [...action.childNodes].find(node => node.nodeType === Node.TEXT_NODE && node.textContent.trim());
          if (label) range.selectNodeContents(label);
          const text = label ? range.getBoundingClientRect() : rect;
          return {
            height: rect.height, fits: rect.left >= bounds.left - 1 && rect.right <= bounds.right + 1,
            nowrap: style.whiteSpace === "nowrap",
            textFits: text.left >= rect.left - 1 && text.right <= rect.right + 1,
            background: style.backgroundColor, border: style.borderColor,
          };
        });
      });
      assert.ok(backupGeometry.every(action => Math.abs(action.height - 44) < 1 &&
        action.fits && action.nowrap && action.textFits),
        `${width}px: backup actions have equal height and single-line labels that fit`);
      assert.equal(new Set(backupGeometry.map(action => action.background + action.border)).size, 1,
        `${width}px: download and restore actions share one style`);
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
      assert.ok(cleanupGeometry.buttonTextNoWrap && cleanupGeometry.buttonWidth >= 170,
        `${width}px: cleanup button text stays on one line`);
      assert.ok(cleanupGeometry.buttonHeight >= 44 && cleanupGeometry.pickerHeight >= 44,
        `${width}px: both controls are convenient to tap`);
      if (width > 760) assert.ok(cleanupGeometry.controlGap <= 2,
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
