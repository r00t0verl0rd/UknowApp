import { apiUrl } from "./api.js";

// A single connection per browser tab, shared by every workspace subscriber.
let source = null;
const subscribers = new Set();
let closeGeneration = 0;
let retryTimer = null;
let watchdog = null;
let lastActivity = 0;

function notify(name, event) {
  for (const subscriber of [...subscribers]) {
    try {
      subscriber[name]?.(event);
    } catch (error) {
      // A broken subscriber must not prevent the others from receiving events.
      console.error("Panel event subscriber failed", error);
    }
  }
}

function openStream() {
  if (source || !subscribers.size || typeof EventSource === "undefined") return;
  const connection = new EventSource(apiUrl("/api/panel/events"), { withCredentials: true });
  source = connection;
  lastActivity = Date.now();
  const touch = () => { if (source === connection) lastActivity = Date.now(); };
  connection.addEventListener("checkpoint", touch);
  connection.addEventListener("heartbeat", touch);
  connection.addEventListener("update", event => {
    if (source !== connection) return;
    touch();
    notify("onUpdate", event);
  });
  connection.onopen = () => {
    if (source !== connection) return;
    touch();
    notify("onOpen");
  };
  connection.onerror = () => {
    if (source !== connection) return;
    notify("onError");
    // EventSource retries network interruptions itself. For terminal failures
    // (e.g. proxy error or invalid response), explicitly create a new stream.
    if (connection.readyState === 2) restart(connection);
  };
  if (watchdog === null) {
    watchdog = setInterval(() => {
      if (!source || Date.now() - lastActivity < 40000) return;
      // An apparently open connection can be stalled by an intermediary.
      // Reconnect and let the normal recovery path reconcile missed events.
      notify("onError");
      restart(source);
    }, 5000);
  }
}

function restart(connection) {
  if (source !== connection) return;
  connection.close();
  source = null;
  if (subscribers.size && retryTimer === null) {
    retryTimer = setTimeout(() => {
      retryTimer = null;
      openStream();
    }, 1500);
  }
}

export function subscribePanelEvents(onUpdate, onOpen, onError) {
  if (typeof EventSource === "undefined") return null;
  closeGeneration += 1;
  const subscriber = { onUpdate, onOpen, onError };
  subscribers.add(subscriber);
  if (source?.readyState === 1) {
    queueMicrotask(() => { if (subscribers.has(subscriber)) onOpen?.(); });
  } else {
    openStream();
  }
  return () => {
    subscribers.delete(subscriber);
    if (!subscribers.size) {
      const generation = ++closeGeneration;
      queueMicrotask(() => {
        if (generation !== closeGeneration || subscribers.size) return;
        clearTimeout(retryTimer);
        clearInterval(watchdog);
        retryTimer = null;
        watchdog = null;
        source?.close();
        source = null;
      });
    }
  };
}
