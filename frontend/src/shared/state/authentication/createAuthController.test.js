import assert from "node:assert/strict";
import test from "node:test";
import { createAuthController } from "./createAuthController.js";

test("login opens workspace immediately even if push permission is slow", async t => {
  const names = ["fetch", "window", "navigator", "Notification", "PushManager", "localStorage", "sessionStorage"];
  const original = Object.fromEntries(names.map(name => [name, Object.getOwnPropertyDescriptor(globalThis, name)]));
  const define = (name, value) => Object.defineProperty(globalThis, name, {
    configurable: true, writable: true, value,
  });
  const store = () => {
    const entries = new Map();
    return {
      getItem: key => entries.get(key) ?? null,
      setItem: (key, value) => entries.set(key, String(value)),
      removeItem: key => entries.delete(key),
    };
  };
  let finishPush;
  const pendingPush = new Promise(resolve => { finishPush = resolve; });
  t.after(() => {
    finishPush({ pushManager: { getSubscription: async () => null } });
    for (const name of names) {
      if (original[name]) Object.defineProperty(globalThis, name, original[name]);
      else delete globalThis[name];
    }
  });
  define("fetch", async url => {
    assert.equal(url, "/api/auth/login");
    return new Response("{}", { status: 200, headers: { "Content-Type": "application/json" } });
  });
  define("window", {
    isSecureContext: true,
    PushManager: class {},
    Notification: class {},
    matchMedia: () => ({ matches: false }),
  });
  define("navigator", {
    userAgent: "node-test",
    platform: "node",
    serviceWorker: { getRegistration: () => pendingPush },
  });
  define("Notification", { permission: "granted" });
  define("PushManager", class {});
  define("localStorage", store());
  define("sessionStorage", store());
  let auth = "";
  let busy = false;
  const authState = {
    login: "school-admin",
    password: "correct-password", // pragma: allowlist secret - fake test-only credential
    get auth() { return auth; },
    setAuth: value => { auth = value; },
    setProfile: () => {},
    setPassword: () => {},
  };
  const controller = createAuthController({
    authState,
    setError: error => { throw new Error(error); },
    setPushBusy: value => { busy = value; },
    setPushState: () => {},
    notify: () => {},
  });
  const signIn = controller.signIn({ preventDefault() {} });
  const settled = await Promise.race([
    signIn.then(() => "ready"),
    new Promise(resolve => setTimeout(() => resolve("still waiting"), 250)),
  ]);
  assert.equal(settled, "ready", "Login must not wait for push registration");
  assert.equal(auth, "1");
  assert.equal(busy, true, "Push setup continues independently");
  assert.equal(globalThis.localStorage.getItem("uknowapp-auth"), "1");
});
