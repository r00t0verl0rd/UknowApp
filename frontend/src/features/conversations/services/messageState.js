const messageId = item => String(item.id);
const timeValue = item => {
  const value = Date.parse(item.created_at || "");
  return Number.isFinite(value) ? value : null;
};

function preserveMonotonicState(previous, incoming) {
  const result = {
    ...previous,
    ...incoming,
    metadata: { ...(previous.metadata || {}), ...(incoming.metadata || {}) },
  };
  const previousRead = Date.parse(previous.panel_read_at || "");
  const incomingRead = Date.parse(incoming.panel_read_at || "");
  if (Number.isFinite(previousRead) && (!Number.isFinite(incomingRead) || previousRead > incomingRead)) {
    result.panel_read_at = previous.panel_read_at;
  }
  if (previous.delivery_status === "delivered" && incoming.delivery_status === "pending") {
    result.delivery_status = previous.delivery_status;
  }
  return result;
}

export function mergeConversationMessages(previous, incoming) {
  if (!incoming.length) return previous;

  const incomingById = new Map();
  for (const item of incoming) incomingById.set(messageId(item), item);
  const clientIds = new Set(
    [...incomingById.values()].map(item => item.metadata?.client_message_id).filter(Boolean),
  );
  const mergedById = new Map();

  for (const item of previous) {
    if (clientIds.has(item.metadata?.client_message_id)) continue;
    const update = incomingById.get(messageId(item));
    mergedById.set(messageId(item), update ? preserveMonotonicState(item, update) : item);
  }
  for (const item of incomingById.values()) {
    if (!mergedById.has(messageId(item))) mergedById.set(messageId(item), item);
  }

  return [...mergedById.values()].sort((left, right) => {
    const leftTime = timeValue(left);
    const rightTime = timeValue(right);
    if (leftTime !== null && rightTime !== null && leftTime !== rightTime) {
      return leftTime - rightTime;
    }
    const leftId = Number(left.id);
    const rightId = Number(right.id);
    return Number.isFinite(leftId) && Number.isFinite(rightId) ? leftId - rightId : 0;
  });
}
