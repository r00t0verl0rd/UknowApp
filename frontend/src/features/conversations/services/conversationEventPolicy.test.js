import test from "node:test";
import assert from "node:assert/strict";
import { applyDeliveryStatus, hasSummaryChanges, requiresMessageSync } from "./conversationEventPolicy.js";

test("read receipts do not refetch the teacher's open conversation", () => {
  assert.equal(requiresMessageSync("read", "teacher", "conversation"), false);
  assert.equal(requiresMessageSync("read", "student", "conversation"), false);
  assert.equal(requiresMessageSync("read", "teacher", "personal"), false);
  assert.equal(requiresMessageSync("read", "admin", "personal"), false);
  assert.equal(requiresMessageSync("read", "admin", "conversation"), true);
});

test("delivery hints avoid full synchronization for all viewers on new Core", () => {
  for (const action of ["upsert", "delete"]) {
    assert.equal(requiresMessageSync(action, "teacher", "conversation"), true);
  }
  assert.equal(requiresMessageSync("delivery", "teacher", "conversation"), false);
  assert.equal(requiresMessageSync("delivery", "student", "conversation"), false);
  assert.equal(requiresMessageSync("delivery", "admin", "conversation", {id: 1}), false);
  assert.equal(requiresMessageSync("delivery", "admin", "conversation"), true);
});

test("a partial delivery hint updates only an already loaded message", () => {
  const rows = [{id: 1, text: "hello"}];
  const merge = (previous, updates) => [{...previous[0], ...updates[0]}];
  assert.equal(applyDeliveryStatus(rows, {id: 2}, merge), rows);
  const status = {id: 1, metadata: {messenger_deliveries: {telegram: {status: "delivered"}}}};
  assert.deepEqual(applyDeliveryStatus(rows, status, merge), [{...rows[0], ...status}]);
});

test("unchanged SSE summaries preserve the existing chat data", () => {
  const old = { id: 3, unread_count: 0, teacher: { id: 7, full_name: "Учитель" }, last_message_at: null };
  assert.equal(hasSummaryChanges(old, { ...old, teacher: { id: 7, full_name: "Учитель" } }), false);
  assert.equal(hasSummaryChanges(old, { unread_count: 1 }), true);
  assert.equal(hasSummaryChanges(old, { teacher: { id: 7, full_name: "Новое имя" } }), true);
  assert.equal(hasSummaryChanges(old, {}), false);
});
