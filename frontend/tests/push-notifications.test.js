import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { runInNewContext } from "node:vm";

const workerSource = readFileSync(new URL("../public/sw.js", import.meta.url), "utf8");

function createWorker({ navigateFails = false } = {}) {
  const listeners = {};
  const actions = [];
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
    addEventListener(name, callback) { listeners[name] = callback; },
    clients: {
      async matchAll() { return [client]; },
      async openWindow(url) { actions.push(["openWindow", url]); },
    },
  };
  runInNewContext(workerSource, { self, URL, setTimeout, clearTimeout });
  return {
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
