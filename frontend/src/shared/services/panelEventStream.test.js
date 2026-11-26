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

test("reopens a terminal EventSource failure rather than waiting for a page reload", async () => {
  const original = globalThis.EventSource;
  const instances = [];
  class FakeEventSource {
    constructor() {
      this.readyState = 0;
      this.listeners = {};
      instances.push(this);
    }
    addEventListener(name, callback) { this.listeners[name] = callback; }
    close() { this.readyState = 2; }
  }
  globalThis.EventSource = FakeEventSource;
  let unsubscribe;
  try {
    const { subscribePanelEvents } = await import("./panelEventStream.js?test=reconnect");
    const messages = [];
    let errors = 0;
    unsubscribe = subscribePanelEvents(event => messages.push(event), null, () => errors++);
    instances[0].readyState = 2;
    instances[0].onerror();
    assert.equal(errors, 1);
    await new Promise(resolve => setTimeout(resolve, 1650));
    assert.equal(instances.length, 2);
    const event = { data: '{"action":"upsert"}' };
    instances[1].listeners.update(event);
    assert.deepEqual(messages, [event]);
  } finally {
    unsubscribe?.();
    await Promise.resolve();
    globalThis.EventSource = original;
  }
});

test("watchdog wakes at the silence deadline and reconnects only a stalled stream", async t => {
  const original = globalThis.EventSource;
  const instances = [];
  class FakeEventSource {
    constructor() {
      this.listeners = {};
      this.readyState = 1;
      instances.push(this);
    }
    addEventListener(name, callback) { this.listeners[name] = callback; }
    close() { this.readyState = 2; }
  }
  globalThis.EventSource = FakeEventSource;
  t.mock.timers.enable({ apis: ["setTimeout", "Date"], now: 0 });
  let unsubscribe;
  try {
    const { subscribePanelEvents } = await import("./panelEventStream.js?test=watchdog");
    let errors = 0;
    unsubscribe = subscribePanelEvents(() => {}, null, () => errors++);
    t.mock.timers.tick(15000);
    instances[0].listeners.heartbeat();
    t.mock.timers.tick(25000);
    assert.equal(errors, 0);
    t.mock.timers.tick(14999);
    assert.equal(errors, 0);
    t.mock.timers.tick(1);
    assert.equal(errors, 1);
    assert.equal(instances[0].readyState, 2);
    t.mock.timers.tick(1500);
    assert.equal(instances.length, 2);
    unsubscribe();
    await Promise.resolve();
    t.mock.timers.tick(80000);
    assert.equal(errors, 1);
    assert.equal(instances.length, 2);
  } finally {
    unsubscribe?.();
    await Promise.resolve();
    t.mock.timers.reset();
    globalThis.EventSource = original;
  }
});
