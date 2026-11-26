import test from "node:test";
import assert from "node:assert/strict";
import { applyDeliveryStatus, applyReadReceipt, hasSummaryChanges, requiresMessageSync } from "./conversationEventPolicy.js";

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


test("read receipts update the reader's other tabs and keep both admin receipts distinct", () => {
  const rows = [
    { id: 1, sender_role: "student", metadata: {}, panel_read_at: null },
    { id: 2, sender_role: "admin", metadata: {}, panel_read_at: null },
  ];
  const first = { actor_role: "teacher", message_ids: [1, 2], read_at: "2026-11-26T10:00:00Z" };
  const read = applyReadReceipt(rows, first, "conversation");
  assert.equal(read[0].panel_read_at, first.read_at);
  assert.equal(read[1].metadata.teacher_read_at, first.read_at);
  assert.equal(read[1].panel_read_at, null);
  assert.equal(applyReadReceipt(read, first, "conversation"), read);
  const second = { actor_role: "student", message_ids: [2], read_at: "2026-11-26T10:01:00Z" };
  const both = applyReadReceipt(read, second, "conversation");
  assert.equal(both[1].panel_read_at, second.read_at);
  assert.equal(both[1].metadata.teacher_read_at, first.read_at);
  const personal = [{ id: 3, sender_role: "admin", panel_read_at: null }];
  assert.equal(applyReadReceipt(personal, { ...second, message_ids: [3] }, "personal")[0].panel_read_at, second.read_at);
});

test("admin observer receipt does not change participants' checkmarks", () => {
  const rows = [
    { id: 1, sender_role: "teacher", admin_read_at: null, panel_read_at: null, metadata: {} },
    { id: 2, sender_role: "student", admin_read_at: null, panel_read_at: null, metadata: {} },
  ];
  const payload = { actor_role: "admin", message_ids: [1], read_at: "2026-11-26T10:00:00Z" };
  const read = applyReadReceipt(rows, payload, "conversation");
  assert.equal(read[0].admin_read_at, payload.read_at);
  assert.equal(read[0].panel_read_at, null);
  assert.deepEqual(read[0].metadata, {});
  assert.equal(read[1], rows[1]);
  assert.equal(applyReadReceipt(read, payload, "conversation"), read);
});
