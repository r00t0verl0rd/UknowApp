/** Friendly, user-facing summaries of optional messenger delivery. */
const names = { telegram: "Telegram", max: "Max", whatsapp: "WhatsApp" };
export function messengerName(platform) {
  return names[platform] || (platform ? platform[0].toUpperCase() + platform.slice(1).toLowerCase() : "Мессенджер");
}
function recipient(error) {
  if (typeof error === "object" && error !== null) {
    if (typeof error.name === "string" && error.name.trim()) return error.name.trim();
    return { teacher: "Преподаватель", student: "Ученик", admin: "Администратор" }[error.role] || "Получатель";
  }
  return "Получатель";
}
function friendlyReason(error, channel) {
  const reason = typeof error === "string" ? error : String(error?.reason || "");
  if (/не подключ|not.connected|not linked|not_connected/i.test(reason)) {
    return channel === "Telegram"
      ? "Получатель не подключил телеграм-бота."
      : `Получатель пока не подключил ${channel}.`;
  }
  if (/не удалось определить адресата|chat not found|чат не найден/i.test(reason)) {
    return `Чат получателя в ${channel} пока не найден.`;
  }
  return `Копию в ${channel} пока не удалось отправить.`;
}
export function getDeliveryDetails(metadata) {
  if (!metadata || typeof metadata !== "object") return [];
  const details = [];
  const deliveries = metadata.messenger_deliveries || {};
  for (const [platform, result] of Object.entries(deliveries)) {
    if (!result || typeof result !== "object") continue;
    const channel = messengerName(platform);
    const delivered = Array.isArray(result.delivered) ? result.delivered : [];
    const errors = Array.isArray(result.errors) ? result.errors : [];
    if (delivered.length) {
      details.push({
        title: channel,
        description: delivered.length === 1 ? "Копия отправлена." : `Отправлено копий: ${delivered.length}.`,
        delivered: true,
      });
    }
    for (const error of errors) {
      details.push({
        title: `${channel} · ${recipient(error)}`,
        description: friendlyReason(error, channel),
        delivered: false,
      });
    }
    if (!delivered.length && !errors.length && result.status === "not_connected") {
      details.push({
        title: channel,
        description: channel === "Telegram" ? "Получатель не подключил телеграм-бота." : "Получатель пока не подключён.",
        delivered: false,
      });
    }
  }
  if (!Object.hasOwn(deliveries, "telegram")) {
    const sent = Array.isArray(metadata.telegram_deliveries) ? metadata.telegram_deliveries : [];
    const errors = Array.isArray(metadata.telegram_delivery_errors) ? metadata.telegram_delivery_errors : [];
    if (sent.length) {
      details.push({
        title: "Telegram",
        description: sent.length === 1 ? "Копия отправлена." : `Отправлено копий: ${sent.length}.`,
        delivered: true,
      });
    }
    for (const error of errors) {
      details.push({
        title: `Telegram · ${recipient(error)}`,
        description: friendlyReason(error, "Telegram"),
        delivered: false,
      });
    }
  }
  return details;
}
