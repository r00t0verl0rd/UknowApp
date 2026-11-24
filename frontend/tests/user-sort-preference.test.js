import assert from "node:assert/strict";
import test from "node:test";
import {
  readUserSortPreference,
  saveUserSortPreference,
} from "../src/shared/services/userSortPreference.js";

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
