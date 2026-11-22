import { apiUrl } from "./api.js";

// Одно SSE-подключение обслуживает все открытые разделы приложения.
let source = null;
const subscribers = new Set();
let closeGeneration = 0;

function openStream() {
  if (source || typeof EventSource === "undefined") return;
  source = new EventSource(apiUrl("/api/panel/events"), { withCredentials: true });
  source.addEventListener("update", event => {
    for (const subscriber of [...subscribers]) subscriber.onUpdate(event);
  });
  source.onopen = () => {
    for (const subscriber of [...subscribers]) subscriber.onOpen?.();
  };
}

export function subscribePanelEvents(onUpdate, onOpen) {
  if (typeof EventSource === "undefined") return null;
  closeGeneration += 1;
  const subscriber = { onUpdate, onOpen };
  subscribers.add(subscriber);
  openStream();
  return () => {
    subscribers.delete(subscriber);
    if (!subscribers.size && source) {
      const generation = ++closeGeneration;
      queueMicrotask(() => {
        if (generation !== closeGeneration || subscribers.size || !source) return;
        source.close();
        source = null;
      });
    }
  };
}
