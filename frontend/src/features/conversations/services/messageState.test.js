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
    mergeConversationMessages([], [{ id: 105, text: "different chat" }], "conversation:41"),
    [{ id: 105, text: "different chat" }],
  );
});

test("older API snapshots cannot roll back read and delivery states", () => {
  const previous = [{
    id: 9,
    text: "message",
    panel_read_at: "2026-11-21T10:00:00Z",
    delivery_status: "delivered",
    metadata: { version: 2 },
  }];
  const stale = [{
    id: 9,
    text: "message",
    panel_read_at: null,
    delivery_status: "pending",
    metadata: { version: 1 },
  }];

  assert.deepEqual(mergeConversationMessages(previous, stale, "conversation:9"), [{
    ...stale[0],
    panel_read_at: previous[0].panel_read_at,
    delivery_status: "delivered",
    metadata: { version: 1 },
  }]);
});
