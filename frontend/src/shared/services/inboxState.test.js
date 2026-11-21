import assert from "node:assert/strict";
import test from "node:test";
import { mergeInboxSnapshot } from "./inboxState.js";

test("keeps an SSE-updated row when an older inbox snapshot resolves", () => {
  const snapshot = [
    { id: 1, unread_count: 0, last_message: "old" },
    { id: 2, unread_count: 0 },
  ];
  const live = [
    { id: 1, unread_count: 3, last_message: "new" },
    { id: 9, unread_count: 1 },
  ];

  assert.deepEqual(mergeInboxSnapshot(snapshot, live), [
    { id: 1, unread_count: 3, last_message: "new" },
    { id: 2, unread_count: 0 },
    { id: 9, unread_count: 1 },
  ]);
});

test("returns the snapshot unchanged when there is no live state", () => {
  const snapshot = [{ id: 1, unread_count: 0 }];
  assert.equal(mergeInboxSnapshot(snapshot, []), snapshot);
});
