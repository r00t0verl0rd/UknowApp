import test from "node:test";
import assert from "node:assert/strict";
import { hasSummaryChanges, requiresMessageSync } from "./conversationEventPolicy.js";

test("read receipts do not refetch the teacher's open conversation", () => {
  assert.equal(requiresMessageSync("read", "teacher", "conversation"), false);
  assert.equal(requiresMessageSync("read", "student", "conversation"), false);
  assert.equal(requiresMessageSync("read", "teacher", "personal"), false);
  assert.equal(requiresMessageSync("read", "admin", "personal"), false);
  assert.equal(requiresMessageSync("read", "admin", "conversation"), true);
});

test("incoming messages, deletions and delivery updates still synchronize", () => {
  for (const action of ["upsert", "delete", "delivery"]) {
    assert.equal(requiresMessageSync(action, "teacher", "conversation"), true);
  }
});

test("unchanged SSE summaries preserve the existing chat data", () => {
  const old = { id: 3, unread_count: 0, teacher: { id: 7, full_name: "Учитель" }, last_message_at: null };
  assert.equal(hasSummaryChanges(old, { ...old, teacher: { id: 7, full_name: "Учитель" } }), false);
  assert.equal(hasSummaryChanges(old, { unread_count: 1 }), true);
  assert.equal(hasSummaryChanges(old, { teacher: { id: 7, full_name: "Новое имя" } }), true);
  assert.equal(hasSummaryChanges(old, {}), false);
});
