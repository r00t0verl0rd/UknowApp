// Даты без часового пояса считаем временем UTC.
export const MESSAGE_DAY_MS = 24 * 60 * 60 * 1000;

export function parseMessageDate(value) {
  if (!value) return null;
  const normalized = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(value) ? value : value + "Z";
  const timestamp = Date.parse(normalized);
  return Number.isFinite(timestamp) ? timestamp : null;
}

export function formatMessageTime(value, nowMs = Date.now()) {
  const timestamp = parseMessageDate(value);
  if (timestamp === null) return "";
  const showDate = nowMs - timestamp >= MESSAGE_DAY_MS;
  const options = showDate
    ? { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }
    : { hour: "2-digit", minute: "2-digit" };
  return new Date(timestamp).toLocaleString("ru-RU", options);
}
