import assert from "node:assert/strict";
import test from "node:test";
import { createConversationCache } from "./conversationCache.js";

function fakeImage() {
  let src = null;
  return {
    complete: true, naturalWidth: 100, naturalHeight: 100,
    getAttribute: name => name === "src" ? src : null,
    removeAttribute: name => { if (name === "src") src = null; },
    addEventListener() {},
    set src(value) { src = value; },
  };
}
const a = "conversation:1";
const b = "personal:1";
function setup(settings = {}) {
  const cache = createConversationCache({ createImage: fakeImage, ...settings });
  cache.setScope("teacher:1", [a, b]);
  return cache;
}
const load = (cache, key, id = 7) => {
  const entry = cache.acquireImage(key, id, "/media/" + id, 100, 100);
  entry.image.src = entry.src;
  cache.releaseImage(entry);
  return entry;
};
test("reuses the original loaded image across dialog switches, not a duplicate request", () => {
  const cache = setup();
  const first = load(cache, a);
  load(cache, b);
  const next = cache.acquireImage(a, 7, "/media/7", 100, 100);
  assert.equal(next, first);
  assert.equal(next.image.getAttribute("src"), "/media/7");
  cache.releaseImage(next);
});
test("idle image count and decoded pixel budget use LRU eviction", () => {
  const cache = setup({ maxIdleImages: 2, maxIdleBytes: 80000 });
  const first = load(cache, a, 1);
  const second = load(cache, a, 2);
  const lease = cache.acquireImage(a, 1, "/media/1", 100, 100);
  assert.equal(lease, first);
  cache.releaseImage(lease);
  load(cache, a, 3);
  assert.equal(second.image.getAttribute("src"), null);
  assert.notEqual(cache.acquireImage(a, 2, "/media/2", 100, 100), second);
});
test("account changes, revocation and deletions purge cached photos and history", () => {
  const cache = setup();
  cache.saveHistory(a, [{ id: 7 }, { id: 8 }], 7);
  const first = load(cache, a);
  const other = load(cache, b);
  cache.removeMessage(a, 7);
  assert.deepEqual(cache.getHistory(a).messages, [{ id: 8 }]);
  assert.equal(first.image.getAttribute("src"), null);
  cache.setScope("teacher:1", [a]);
  assert.equal(other.image.getAttribute("src"), null);
  const mounted = cache.acquireImage(a, 8, "/media/8", 100, 100);
  mounted.image.src = mounted.src;
  cache.setScope("student:2", [a]);
  cache.releaseImage(mounted);
  assert.equal(mounted.image.getAttribute("src"), null);
  assert.equal(cache.getHistory(a), null);
  assert.notEqual(cache.acquireImage(a, 8, "/media/8", 100, 100), mounted);
});
test("history keeps pagination cursor, caches empty chats, expires and stays bounded", () => {
  let time = 0;
  const cache = setup({ now: () => time, maxChats: 1, historyTtl: 100 });
  cache.saveHistory(a, [], 0);
  assert.deepEqual(cache.getHistory(a).messages, []);
  cache.saveHistory(b, [{ id: 5 }], 5);
  assert.equal(cache.getHistory(a), null);
  assert.equal(cache.getHistory(b).olderCursor, 5);
  time = 101;
  assert.equal(cache.getHistory(b), null);
});
test("a duplicate mounted owner cannot steal the cached DOM node", () => {
  const cache = setup();
  const first = cache.acquireImage(a, 7, "/media/7", 100, 100);
  const duplicate = cache.acquireImage(a, 7, "/media/7", 100, 100);
  assert.notEqual(duplicate.image, first.image);
  first.image.src = first.src;
  cache.releaseImage(duplicate);
  cache.releaseImage(first);
  assert.equal(cache.acquireImage(a, 7, "/media/7", 100, 100), first);
});
