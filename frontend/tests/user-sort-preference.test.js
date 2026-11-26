import assert from "node:assert/strict";
import test from "node:test";
import {
  readUserSortPreference,
  saveUserSortPreference,
} from "../src/shared/services/userSortPreference.js";
import { readViewState, saveViewPreference, saveViewPreferences } from "../src/shared/services/viewSession.js";

function memoryStorage() {
  const map = new Map();
  return {
    getItem:key => map.has(key) ? map.get(key) : null,
    setItem:(key,value) => map.set(key,String(value)),
  };
}

test("the admin's selected user sort persists and is isolated by account", () => {
  const store = memoryStorage();
  assert.equal(readUserSortPreference(7,"students",store),"students");
  saveUserSortPreference(7,"teachers",store);
  assert.equal(readUserSortPreference(7,"students",store),"teachers");
  assert.equal(readUserSortPreference(8,"students",store),"students");
  for (const option of ["name-asc", "name-desc", "students"]) {
    saveUserSortPreference(7,option,store);
    assert.equal(readUserSortPreference(7,"teachers",store),option);
  }
});

test("invalid sort keys and disabled storage do not break sorting", () => {
  const store = memoryStorage();
  saveUserSortPreference(7,"teachers",store);
  saveUserSortPreference(7,"__unexpected__",store);
  assert.equal(readUserSortPreference(7,"students",store),"teachers");
  assert.equal(readUserSortPreference(null,"students",store),"students");
  const blocked = {
    getItem() { throw new Error("storage blocked"); },
    setItem() { throw new Error("storage blocked"); },
  };
  assert.equal(readUserSortPreference(7,"students",blocked),"students");
  assert.doesNotThrow(() => saveUserSortPreference(7,"teachers",blocked));
});

test("view preferences persist together and skip identical writes", t => {
  const original = Object.getOwnPropertyDescriptor(globalThis, "sessionStorage");
  const store = memoryStorage();
  let writes = 0;
  Object.defineProperty(globalThis, "sessionStorage", {
    configurable: true, value: {
      getItem: store.getItem,
      setItem(key, value) { writes++; store.setItem(key, value); },
    },
  });
  t.after(() => {
    if (original) Object.defineProperty(globalThis, "sessionStorage", original);
    else delete globalThis.sessionStorage;
  });
  saveViewPreference(7, "chats.active", "personal:5");
  const patch = { "chats.search": "name", "chats.filter": "unread", "users.sort": "teachers" };
  saveViewPreferences(7, patch);
  assert.equal(writes, 2);
  saveViewPreferences(7, patch);
  assert.equal(writes, 2);
  assert.deepEqual(readViewState(7).preferences, { "chats.active": "personal:5", ...patch });
  assert.deepEqual(readViewState(8), {});
});
