import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { runInNewContext } from "node:vm";

const workerSource = readFileSync(new URL("../public/sw.js", import.meta.url), "utf8");

function createWorker({ navigateFails = false } = {}) {
  const listeners = {};
  const actions = [];
  const notifications = [];
  const client = {
    url: "https://uknowschool.ru/",
    focused: true,
    async navigate(url) {
      actions.push(["navigate", url]);
      if (navigateFails) throw new Error("window not navigable");
      return { async focus() { actions.push(["focus"]); } };
    },
  };
  const self = {
    location: { origin: "https://uknowschool.ru" },
    registration: {
      async showNotification(title, options) { notifications.push({ title, options }); },
    },
    addEventListener(name, callback) { listeners[name] = callback; },
    clients: {
      async matchAll() { return [client]; },
      async openWindow(url) { actions.push(["openWindow", url]); },
    },
  };
  runInNewContext(workerSource, {
    self, URL, setTimeout, clearTimeout,
    fetch: async () => ({ ok: true, headers: { get: () => "application/json" } }),
  });
  return {
    async push(payload) {
      let pending;
      listeners.push({
        data: { json: () => payload },
        waitUntil(task) { pending = task; },
      });
      await pending;
      return notifications.at(-1);
    },
    async click(url) {
      let pending;
      listeners.notificationclick({
        notification: { data: { url }, close() { actions.push(["close"]); } },
        waitUntil(task) { pending = task; },
      });
      await pending;
      return actions;
    },
  };
}

test("push replaces the duplicated app-name title with «Сообщение»", async () => {
  const notification = await createWorker().push({
    title: "UknowApp",
    body: "Падаван",
    conversation_id: 17,
    conversation_type: "conversation",
  });
  assert.equal(notification.title, "Сообщение");
  assert.equal(notification.options.body, "Падаван");
});

test("admin push keeps message direction in the body", async () => {
  const notification = await createWorker().push({
    title: "",
    body: "Ученик Иван → Учитель Анна",
    conversation_id: 17,
    conversation_type: "conversation",
  });
  assert.equal(notification.title, "Сообщение");
  assert.equal(notification.options.body, "Ученик Иван → Учитель Анна");
});

test("missing push title and body are not duplicated", async () => {
  const notification = await createWorker().push({
    title: "",
    body: " ",
    conversation_id: 17,
    conversation_type: "conversation",
  });
  assert.equal(notification.title, "Сообщение");
  assert.equal(Object.hasOwn(notification.options, "body"), false);
});

test("explicit non-app notification titles are preserved", async () => {
  const notification = await createWorker().push({
    title: "Домашнее задание",
    body: "Учитель Анна",
    conversation_id: 17,
    conversation_type: "conversation",
  });
  assert.equal(notification.title, "Домашнее задание");
  assert.equal(notification.options.body, "Учитель Анна");
});

test("push click opens the exact participant conversation", async () => {
  const actions = await createWorker().click("/?openConversation=17");
  assert.deepEqual(actions, [
    ["close"],
    ["navigate", "https://uknowschool.ru/?openConversation=17"],
    ["focus"],
  ]);
});

test("push click opens the personal conversation with its type", async () => {
  const actions = await createWorker().click("/?openConversation=21&type=personal");
  assert.equal(actions[1][1], "https://uknowschool.ru/?openConversation=21&type=personal");
});

test("push click falls back to opening a window if navigation fails", async () => {
  const actions = await createWorker({ navigateFails: true }).click("/?openConversation=30");
  assert.deepEqual(actions[2], ["openWindow", "https://uknowschool.ru/?openConversation=30"]);
});

test("push click never opens a different origin", async () => {
  const actions = await createWorker().click("//other.example/phishing");
  assert.deepEqual(actions[1], ["navigate", "https://uknowschool.ru/"]);
});

test("iPhone Safari explains Home Screen installation before missing push APIs", () => {
  const source = readFileSync(new URL("../src/features/notifications/pushNotifications.js", import.meta.url), "utf8");
  const supportSource = source.slice(source.indexOf("function getPushSupport()"), source.indexOf("function decodeApplicationServerKey"));
  const mobile = {
    isSecureContext: true,
    matchMedia: () => ({ matches: false }),
  };
  const ios = {
    userAgent: "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X)",
    standalone: false,
    platform: "iPhone",
    maxTouchPoints: 5,
  };
  const safari = runInNewContext(supportSource + "\ngetPushSupport()", { window: mobile, navigator: ios });
  assert.equal(safari.supported, false);
  assert.match(safari.reason, /«На экран Домой»/);
  assert.doesNotMatch(safari.reason, /не поддерживает push/);
  assert.doesNotMatch(safari.reason, /запрещен/i);

  const installed = runInNewContext(supportSource + "\ngetPushSupport()", {
    window: { isSecureContext: true, matchMedia: () => ({ matches: true }), PushManager: function () {}, Notification: function () {} },
    navigator: { ...ios, standalone: true, serviceWorker: {} },
  });
  assert.equal(installed.supported, true);
});
test("unsupported push uses informational feedback, not a success toast", () => {
  const state = readFileSync(new URL("../src/shared/state/notifications/createPushNotificationsState.js", import.meta.url), "utf8");
  const toast = readFileSync(new URL("../src/shared/components/AppToast.jsx", import.meta.url), "utf8");
  assert.match(state, /options\.notify\(pushState\(\)\.reason, \{ kind: "info" \}\)/);
  assert.match(toast, /native-feedback-info/);
  assert.match(toast, /isInfo\(\) \? "Уведомления" : "Готово"/);
});

test("notification permission messages are gentle and actionable", () => {
  const source = readFileSync(new URL("../src/features/notifications/pushNotifications.js", import.meta.url), "utf8");
  const state = readFileSync(new URL("../src/shared/state/notifications/createPushNotificationsState.js", import.meta.url), "utf8");
  assert.doesNotMatch(source + state, /запрещен[а-яё]*/i);
  assert.doesNotMatch(source + state, /браузер не разрешил/i);
  assert.match(state, /Уведомления отключены в настройках устройства\. Разрешите их для UknowApp и попробуйте снова\./);
  assert.match(state, /Уведомления отключены в настройках браузера/);
  assert.match(source, /В этом браузере уведомления пока недоступны/);
});
