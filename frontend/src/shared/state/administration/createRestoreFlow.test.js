import assert from "node:assert/strict";
import test from "node:test";
import { readRestoreFlow, RESTORE_FLOW_KEY } from "./createRestoreFlow.js";

function storage() {
  const items = new Map();
  return {
    getItem: key => items.get(key) ?? null,
    setItem: (key, value) => items.set(key, value),
    removeItem: key => items.delete(key),
  };
}

test("accepted restore ID survives a reload without storing the archive or credentials", () => {
  const store = storage();
  store.setItem(RESTORE_FLOW_KEY, JSON.stringify({
    id: "unique-restore-id", phase: "reauth", startedAt: 100,
    automaticRestart: true,
  }));
  assert.deepEqual(readRestoreFlow(store, 200), {
    id: "unique-restore-id", phase: "reauth", startedAt: 100,
    automaticRestart: true,
  });
});

test("invalid, expired and unexpected restore markers do not block the application", () => {
  const store = storage();
  store.setItem(RESTORE_FLOW_KEY, "not JSON");
  assert.equal(readRestoreFlow(store), null);
  store.setItem(RESTORE_FLOW_KEY, JSON.stringify({
    id: "expired", phase: "waiting", startedAt: 100,
  }));
  assert.equal(readRestoreFlow(store, 2 * 24 * 60 * 60 * 1000), null);
  assert.equal(store.getItem(RESTORE_FLOW_KEY), null);
  store.setItem(RESTORE_FLOW_KEY, JSON.stringify({
    id: "unexpected", phase: "root", startedAt: 100,
  }));
  assert.equal(readRestoreFlow(store, 200), null);
});
