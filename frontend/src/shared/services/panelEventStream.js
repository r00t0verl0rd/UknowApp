let source = null;
const subscribers = new Set();

function openStream() {
  if (source || typeof EventSource === "undefined") return;
  const API = import.meta.env?.VITE_API_BASE_URL || "";
  source = new EventSource(API + "/api/panel/events", { withCredentials: true });
  source.addEventListener("update", event => {
    for (const subscriber of [...subscribers]) subscriber.onUpdate(event);
  });
  source.onopen = () => {
    for (const subscriber of [...subscribers]) subscriber.onOpen?.();
  };
}

export function subscribePanelEvents(onUpdate, onOpen) {
  if (typeof EventSource === "undefined") return null;
  const subscriber = { onUpdate, onOpen };
  subscribers.add(subscriber);
  openStream();
  return () => {
    subscribers.delete(subscriber);
    if (!subscribers.size && source) {
      source.close();
      source = null;
    }
  };
}
