import assert from "node:assert/strict";
import test from "node:test";
import {
  markConversationMessageDeleted,
  mergeConversationMessages,
} from "./messageState.js";

test("a deleted message cannot be reintroduced by a late history response", () => {
  const scope = "conversation:41";
  markConversationMessageDeleted(scope, 105);
  assert.deepEqual(
    mergeConversationMessages([], [
      { id: 104, text: "still here" },
      { id: 105, text: "deleted" },
    ], scope),
    [{ id: 104, text: "still here" }],
  );
});

test("message tombstones are isolated by conversation", () => {
  markConversationMessageDeleted("personal:41", 105);
  assert.deepEqual(
    mergeConversationMessages([], [{ id: 105, text: "different chat" }], "conversation:42"),
    [{ id: 105, text: "different chat" }],
  );
});

test("older API snapshots cannot roll back read or delivered state", () => {
  const result = mergeConversationMessages(
    [{
      id: 7,
      delivery_status: "delivered",
      panel_read_at: "2026-11-21T10:03:00Z",
    }],
    [{
      id: 7,
      delivery_status: "pending",
      panel_read_at: "2026-11-21T10:01:00Z",
    }],
    "conversation:7",
  );
  assert.equal(result[0].delivery_status, "delivered");
  assert.equal(result[0].panel_read_at, "2026-11-21T10:03:00Z");
});

test("duplicate updates are collapsed and messages remain chronological", () => {
  const result = mergeConversationMessages(
    [{ id: 2, created_at: "2026-11-21T10:02:00Z", text: "second" }],
    [
      { id: 1, created_at: "2026-11-21T10:01:00Z", text: "first" },
      { id: 2, created_at: "2026-11-21T10:02:00Z", text: "updated" },
      { id: 2, created_at: "2026-11-21T10:02:00Z", text: "latest" },
    ],
    "conversation:2",
  );
  assert.deepEqual(result.map(item => item.id), [1, 2]);
  assert.equal(result[1].text, "latest");
});

test("server echo replaces optimistic client message without duplication", () => {
  const result = mergeConversationMessages(
    [{ id: "local-1", metadata: { client_message_id: "client-1" }, text: "hello" }],
    [{ id: 15, metadata: { client_message_id: "client-1" }, text: "hello" }],
    "conversation:15",
  );
  assert.equal(result.length, 1);
  assert.equal(result[0].id, 15);
});

test("terminal delivery and metadata read markers never move backwards", () => {
  const result = mergeConversationMessages(
    [{
      id: 21,
      delivery_status: "blocked_contact",
      metadata: { teacher_read_at: "2026-11-21T10:05:00Z" },
    }],
    [{
      id: 21,
      delivery_status: "delivered",
      metadata: { teacher_read_at: "2026-11-21T10:01:00Z" },
    }],
    "conversation:21",
  );
  assert.equal(result[0].delivery_status, "blocked_contact");
  assert.equal(result[0].metadata.teacher_read_at, "2026-11-21T10:05:00Z");
});

test("repeated status sync reuses the loaded history and its message objects", () => {
  const previous = [{ id: 9, text: "hello", panel_read_at: null }];
  const updated = mergeConversationMessages(previous, [{ id: 9, panel_read_at: null }]);
  assert.equal(updated, previous);
});

test("a repeated server echo with a client ID preserves confirmed read state", () => {
  const metadata = { client_message_id: "client-9" };
  const previous = [{ id: 9, metadata, panel_read_at: "2026-11-21T10:03:00Z" }];
  const updated = mergeConversationMessages(previous, [{ id: 9, metadata, panel_read_at: null }]);
  assert.equal(updated[0].panel_read_at, previous[0].panel_read_at);
});
