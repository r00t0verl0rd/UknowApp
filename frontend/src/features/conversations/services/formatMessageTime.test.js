import assert from "node:assert/strict";
import test from "node:test";
import { formatMessageTime, MESSAGE_DAY_MS, parseMessageDate } from "./formatMessageTime.js";

test("recent messages show only the local hour and minute", () => {
  const now = Date.UTC(2026, 10, 22, 12, 30);
  const timestamp = new Date(now - MESSAGE_DAY_MS + 1).toISOString();
  const expected = new Date(timestamp).toLocaleString("ru-RU", {
    hour: "2-digit", minute: "2-digit",
  });
  assert.equal(formatMessageTime(timestamp, now), expected);
});

test("messages exactly 24 hours old and older show date and time", () => {
  const now = Date.UTC(2026, 10, 22, 12, 30);
  for (const age of [MESSAGE_DAY_MS, 3 * MESSAGE_DAY_MS]) {
    const timestamp = new Date(now - age).toISOString();
    const expected = new Date(timestamp).toLocaleString("ru-RU", {
      day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit",
    });
    assert.equal(formatMessageTime(timestamp, now), expected);
  }
});

test("naive timestamps are interpreted as UTC and offsets are preserved", () => {
  assert.equal(parseMessageDate("2026-11-22T09:15:00"), Date.parse("2026-11-22T09:15:00Z"));
  assert.equal(parseMessageDate("2026-11-22T12:15:00+03:00"), Date.parse("2026-11-22T09:15:00Z"));
  assert.equal(formatMessageTime(null), "");
  assert.equal(formatMessageTime("not-a-date"), "");
});
