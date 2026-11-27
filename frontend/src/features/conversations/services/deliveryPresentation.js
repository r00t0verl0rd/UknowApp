/** Friendly, user-facing summaries of optional messenger delivery. */
const names = { telegram: "Telegram", max: "MAX", whatsapp: "WhatsApp" };
export function messengerName(platform) {
  return names[platform] || (platform ? platform[0].toUpperCase() + platform.slice(1).toLowerCase() : "Мессенджер");
}
function recipient(error, participants = []) {
  if (typeof error === "object" && error !== null) {
    if (typeof error.name === "string" && error.name.trim()) return error.name.trim();
    const match = participants.find(person => Number(person.id) === Number(error.user_id) && person.id != null);
    if (typeof match?.full_name === "string" && match.full_name.trim()) return match.full_name.trim();
    return { teacher: "Преподаватель", student: "Ученик", admin: "Администратор" }[error.role] || "Получатель";
  }
  return "Получатель";
}
function deliveryDestination(entry) {
  return entry?.external_thread_id ? "во вкладку в группе"
    : entry?.endpoint_type === "group" ? "в группу"
    : entry?.endpoint_type === "private" ? "в личный чат с ботом"
    : "";
}
function deliveredEntries(channel, delivered, includeRecipient, participants) {
  if (!includeRecipient) return [{
    title: channel,
    description: delivered.length === 1 ? "Копия отправлена." : `Отправлено копий: ${delivered.length}.`,
    delivered: true,
  }];
  const destinations = delivered.filter((entry, index) => {
    if (entry?.external_chat_id == null) return true;
    return delivered.findIndex(copy => copy?.external_chat_id === entry.external_chat_id &&
      copy.external_thread_id === entry.external_thread_id && copy.user_id === entry.user_id) === index;
  });
  return destinations.map((entry) => {
    const name = recipient(entry, participants);
    const person = participants.find(p => p.id != null && Number(p.id) === Number(entry?.user_id));
    const role = entry?.role || person?.role;
    const destination = deliveryDestination(entry);
    const description = destination ? `Копия отправлена ${destination}.`
      : destinations.length > 1 ? "Копия отправлена. Место доставки не записано." : "Копия отправлена.";
    return {
      title: `${channel} · ${name}`,
      ...(name !== "Получатель" ? { namedRecipient: name, role, channel } : {}),
      description,
      delivered: true,
    };
  });
}
function friendlyReason(error, channel) {
  const destination = deliveryDestination(error);
  const address = destination ? `${destination} (${channel})` : `в ${channel}`;
  const reason = typeof error === "string" ? error : String(error?.reason || "");
  if (/не подключ|not.connected|not linked|not_connected/i.test(reason)) {
    if (destination) return `Копия ${address} не отправлена: получатель не подключён.`;
    return channel === "Telegram"
      ? "Получатель не подключил телеграм-бота."
      : `Получатель пока не подключил ${channel}.`;
  }
  if (/не удалось определить адресата|chat not found|чат не найден/i.test(reason)) {
    if (destination) return `Копия ${address} не отправлена: чат получателя не найден.`;
    return `Чат получателя в ${channel} пока не найден.`;
  }
  if (reason === "unknown") return `Не удалось подтвердить отправку копии ${address}.`;
  if (reason === "cancelled") return `Отправка копии ${address} отменена.`;
  return `Копию ${address} пока не удалось отправить.`;
}
export function getDeliveryDetails(metadata, includeRecipient = false, participants = []) {
  if (!metadata || typeof metadata !== "object") return [];
  const details = [];
  const deliveries = metadata.messenger_deliveries || {};
  for (const [platform, result] of Object.entries(deliveries)) {
    if (!result || typeof result !== "object") continue;
    const channel = messengerName(platform);
    const delivered = Array.isArray(result.delivered) ? result.delivered : [];
    const errors = Array.isArray(result.errors) ? result.errors : [];
    if (delivered.length) {
      details.push(...deliveredEntries(channel, delivered, includeRecipient, participants));
    }
    for (const error of errors) {
      details.push({
        title: `${channel} · ${recipient(error, participants)}`,
        ...(includeRecipient && recipient(error, participants) !== "Получатель" ? {
          namedRecipient: recipient(error, participants),
          role: error.role || participants.find(person => Number(person.id) === Number(error?.user_id))?.role,
          channel,
        } : {}),
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
      details.push(...deliveredEntries("Telegram", sent, includeRecipient, participants));
    }
    for (const error of errors) {
      details.push({
        title: `Telegram · ${recipient(error, participants)}`,
        ...(includeRecipient && recipient(error, participants) !== "Получатель" ? {
          namedRecipient: recipient(error, participants),
          role: error.role || participants.find(person => Number(person.id) === Number(error?.user_id))?.role,
          channel: "Telegram",
        } : {}),
        description: friendlyReason(error, "Telegram"),
        delivered: false,
      });
    }
  }
  return details;
}
