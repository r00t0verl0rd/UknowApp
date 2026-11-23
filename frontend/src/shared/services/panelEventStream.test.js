import assert from "node:assert/strict";
import test from "node:test";

test("shares one EventSource and closes it after the final subscriber leaves", async () => {
  const original = globalThis.EventSource;
  const instances = [];
  class FakeEventSource {
    constructor(url, options) {
      this.url = url;
      this.options = options;
      this.listeners = {};
      this.closed = false;
      instances.push(this);
    }
    addEventListener(name, callback) { this.listeners[name] = callback; }
    close() { this.closed = true; }
  }
  globalThis.EventSource = FakeEventSource;
  try {
    const { subscribePanelEvents } = await import("./panelEventStream.js?test=shared");
    const firstEvents = [];
    const secondEvents = [];
    const unsubscribeFirst = subscribePanelEvents(event => firstEvents.push(event));
    const unsubscribeSecond = subscribePanelEvents(event => secondEvents.push(event));
    assert.equal(instances.length, 1);
    assert.equal(instances[0].url, "/api/panel/events");
    assert.equal(instances[0].options.withCredentials, true);
    const event = { data: "{}" };
    instances[0].listeners.update(event);
    assert.deepEqual(firstEvents, [event]);
    assert.deepEqual(secondEvents, [event]);
    unsubscribeFirst();
    assert.equal(instances[0].closed, false);
    unsubscribeSecond();
    assert.equal(instances[0].closed, false);
    const unsubscribeThird = subscribePanelEvents(() => {});
    assert.equal(instances.length, 1);
    assert.equal(instances[0].closed, false);
    unsubscribeThird();
    await Promise.resolve();
    assert.equal(instances[0].closed, true);
  } finally {
    globalThis.EventSource = original;
  }
});
