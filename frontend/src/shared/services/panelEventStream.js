import { apiUrl } from "./api.js";

// Одно SSE-соединение на вкладку для всех разделов кабинета.
let source = null;
const subscribers = new Set();
let closeGeneration = 0;
let retryTimer = null;
let watchdog = null;
let lastActivity = 0;
const STALL_TIMEOUT = 40000;

function notify(name, event) {
  for (const subscriber of [...subscribers]) {
    try {
      subscriber[name]?.(event);
    } catch (error) {
      // Ошибка одного подписчика не блокирует остальных.
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
    // При окончательном сбое создаём новое SSE-соединение.
    if (connection.readyState === 2) restart(connection);
  };
  watchdog = setTimeout(checkWatchdog, STALL_TIMEOUT);
}

function checkWatchdog() {
  watchdog = null;
  const connection = source;
  if (!connection) return;
  const remaining = STALL_TIMEOUT - (Date.now() - lastActivity);
  if (remaining > 0) {
    watchdog = setTimeout(checkWatchdog, Math.min(remaining, STALL_TIMEOUT));
    return;
  }
  // Проверяем, что открытое соединение не зависло.
  notify("onError");
  restart(connection);
}

function restart(connection) {
  if (source !== connection) return;
  clearTimeout(watchdog);
  watchdog = null;
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
        clearTimeout(watchdog);
        retryTimer = null;
        watchdog = null;
        source?.close();
        source = null;
      });
    }
  };
}
