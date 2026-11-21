import assert from "node:assert/strict";
import test from "node:test";
import { mergeConversationMessages } from "./messageState.js";

test("merges messages once and keeps chronological order", () => {
  const result = mergeConversationMessages(
    [{ id: 2, created_at: "2026-11-21T10:02:00Z", text: "second" }],
    [
      { id: 1, created_at: "2026-11-21T10:01:00Z", text: "first" },
      { id: 2, created_at: "2026-11-21T10:02:00Z", text: "updated" },
      { id: 2, created_at: "2026-11-21T10:02:00Z", text: "latest" },
    ],
  );
  assert.deepEqual(result.map(item => item.id), [1, 2]);
  assert.equal(result[1].text, "latest");
});

test("older API snapshots cannot roll back read or delivered state", () => {
  const result = mergeConversationMessages(
    [{ id: 7, delivery_status: "delivered", panel_read_at: "2026-11-21T10:03:00Z" }],
    [{ id: 7, delivery_status: "pending", panel_read_at: "2026-11-21T10:01:00Z" }],
  );
  assert.equal(result[0].delivery_status, "delivered");
  assert.equal(result[0].panel_read_at, "2026-11-21T10:03:00Z");
});

test("server echo replaces optimistic client message without duplication", () => {
  const result = mergeConversationMessages(
    [{ id: "local-1", metadata: { client_message_id: "client-1" }, text: "hello" }],
    [{ id: 15, metadata: { client_message_id: "client-1" }, text: "hello" }],
  );
  assert.equal(result.length, 1);
  assert.equal(result[0].id, 15);
});
