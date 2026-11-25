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
    body: "от Падаван",
    conversation_id: 17,
    conversation_type: "conversation",
  });
  assert.equal(notification.title, "Сообщение");
  assert.equal(notification.options.body, "от Падаван");
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


// Real subscription controller, fake browser and Core. Each import has its own
// device-local state, like separate installed PWAs.
let deviceModule = 0;
async function mockDevice(t, {existing = true, expired = false, oldKey = false, permission = "granted"} = {}) {
  const names = ["window", "navigator", "Notification", "localStorage", "fetch"];
  const originals = Object.fromEntries(names.map(name => [name, Object.getOwnPropertyDescriptor(globalThis, name)]));
  const define = (name, value) => Object.defineProperty(globalThis, name, { configurable:true, writable:true, value });
  t.after(() => {
    for (const name of names) {
      if (originals[name]) Object.defineProperty(globalThis, name, originals[name]);
      else delete globalThis[name];
    }
  });
  const calls = [];
  const server = new Set();
  const storage = new Map();
  const key = Uint8Array.from([1,2,3]);
  let current = null;
  let next = 1;
  let dead = expired;
  let fail = false;
  let prompts = 0;
  function makeSubscription(endpoint, applicationServerKey = key) {
    return {
      endpoint, options: { applicationServerKey: applicationServerKey.buffer }, expirationTime:null,
      toJSON() { return { endpoint, keys: { p256dh:"key", auth:"auth" } }; },
      async unsubscribe() { calls.push(["unsubscribe", endpoint]); if (current === this) current = null; return true; },
    };
  }
  if (existing) current = makeSubscription("old", oldKey ? Uint8Array.from([4,5,6]) : key);
  const registration = { active:true, pushManager:{
    async getSubscription() { return current; },
    async subscribe() { current = makeSubscription("new-" + next++); calls.push(["create",current.endpoint]); return current; },
  } };
  define("window", { isSecureContext:true, PushManager:class {}, Notification:class {}, matchMedia:()=>({matches:false}) });
  define("navigator", { userAgent:"test", platform:"test", serviceWorker:{
    async getRegistration() { return registration; },
  } });
  define("Notification", { permission, async requestPermission() { prompts++; return "granted"; } });
  define("localStorage", {getItem:key=>storage.get(key)??null,setItem:(key,value)=>storage.set(key,value),removeItem:key=>storage.delete(key)});
  const json = (body, status=200) => new Response(JSON.stringify(body), { status });
  define("fetch", async (url, options) => {
    if (url === "/api/push/public-key") return json({enabled:true,public_key:"AQID"});
    assert.equal(url, "/api/push/subscribe");
    const endpoint = JSON.parse(options.body).endpoint;
    calls.push([options.method, endpoint]);
    if (fail) return json({detail:"unavailable"},503);
    if (options.method === "DELETE") { server.delete(endpoint); return json({ok:true}); }
    if (dead && endpoint === "old") return json({},410);
    server.add(endpoint);
    return json({ok:true});
  });
  const module = await import("../src/features/notifications/pushNotifications.js?device=" + (++deviceModule));
  return { module,calls,server,storage,get prompts(){return prompts;}, setFailure(value){fail=value;}, get current(){return current;} };
}

test("opening app registers an existing local subscription even if Core lost it", async t => {
  const d = await mockDevice(t);
  assert.equal((await d.module.getPushNotificationState()).enabled,false);
  await d.module.syncPushNotifications();
  assert.deepEqual([...d.server],["old"]);
  assert.equal((await d.module.getPushNotificationState()).enabled,true);
  d.server.clear();
  await d.module.syncPushNotifications();
  assert.deepEqual([...d.server],["old"]);
  assert.equal(d.calls.filter(c=>c[0]==="create").length,0);
});

test("expired provider subscription is recreated and confirmed", async t => {
  const d = await mockDevice(t,{expired:true});
  await d.module.syncPushNotifications();
  assert.deepEqual(d.calls,[["POST","old"],["unsubscribe","old"],["create","new-1"],["POST","new-1"],["DELETE","old"]]);
  assert.equal((await d.module.getPushNotificationState()).enabled,true);
});

test("changed VAPID key replaces the old subscription", async t => {
  const d = await mockDevice(t,{oldKey:true});
  await d.module.syncPushNotifications();
  assert.deepEqual(d.calls,[["unsubscribe","old"],["create","new-1"],["POST","new-1"],["DELETE","old"]]);
});

test("missing local subscription is recreated when permission is granted", async t => {
  const d = await mockDevice(t,{existing:false});
  await d.module.syncPushNotifications();
  assert.deepEqual(d.calls,[["create","new-1"],["POST","new-1"]]);
  assert.equal(d.prompts,0);
});

test("automatic sync does not prompt or undo a manual opt-out", async t => {
  const d = await mockDevice(t,{permission:"default"});
  await d.module.syncPushNotifications();
  assert.equal(d.prompts,0);
  Notification.permission = "granted";
  await d.module.syncPushNotifications();
  await d.module.disablePushNotifications();
  const count = d.calls.length;
  await d.module.syncPushNotifications({login:true,requestPermission:true});
  assert.equal(d.calls.length,count);
  assert.equal((await d.module.getPushNotificationState()).enabled,false);
  await d.module.enablePushNotifications();
  assert.equal((await d.module.getPushNotificationState()).enabled,true);
});

test("a failed server sync never claims enabled; next foreground can repair it", async t => {
  const d = await mockDevice(t);
  d.setFailure(true);
  await assert.rejects(d.module.syncPushNotifications(),/unavailable/);
  assert.equal((await d.module.getPushNotificationState()).enabled,false);
  d.setFailure(false);
  await d.module.syncPushNotifications();
  assert.equal((await d.module.getPushNotificationState()).enabled,true);
});

test("logout detaches only the current endpoint even after a network failure", async t => {
  const d = await mockDevice(t);
  d.server.add("other-device");
  await d.module.syncPushNotifications();
  await d.module.detachPushSubscription();
  assert.deepEqual([...d.server],["other-device"]);
  assert.equal(d.current,null);
  const count = d.calls.length;
  await d.module.syncPushNotifications();
  assert.equal(d.calls.length,count);
  await d.module.syncPushNotifications({login:true});
  assert.equal((await d.module.getPushNotificationState()).enabled,true);
  d.setFailure(true);
  await d.module.detachPushSubscription();
  assert.equal(d.current,null);
  assert.equal((await d.module.getPushNotificationState()).enabled,false);
});
