const deletedByConversation = new Map();
const MAX_DELETED_IDS = 5000;
const MAX_TOMBSTONE_CONVERSATIONS = 100;

export function markConversationMessageDeleted(conversationKey, messageId) {
  if (!conversationKey || !Number.isSafeInteger(Number(messageId))) return;
  let deleted = deletedByConversation.get(conversationKey);
  if (!deleted) {
    if (deletedByConversation.size >= MAX_TOMBSTONE_CONVERSATIONS) {
      deletedByConversation.delete(deletedByConversation.keys().next().value);
    }
    deleted = new Set();
    deletedByConversation.set(conversationKey, deleted);
  }
  deleted.add(String(messageId));
  if (deleted.size > MAX_DELETED_IDS) {
    deleted.delete(deleted.values().next().value);
  }
}

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
  const previousStatus = previous.delivery_status;
  if (previousStatus && previousStatus !== "pending" && incoming.delivery_status !== previousStatus) {
    result.delivery_status = previousStatus;
  }
  for (const key of ["teacher_read_at", "student_read_at"]) {
    const previousReadAt = Date.parse(previous.metadata?.[key] || "");
    const incomingReadAt = Date.parse(incoming.metadata?.[key] || "");
    if (Number.isFinite(previousReadAt)
      && (!Number.isFinite(incomingReadAt) || previousReadAt > incomingReadAt)) {
      result.metadata[key] = previous.metadata[key];
    }
  }
  return result;
}

export function mergeConversationMessages(previous, incoming, conversationKey = "") {
  const deleted = deletedByConversation.get(conversationKey);
  const visiblePrevious = deleted
    ? previous.filter(item => !deleted.has(messageId(item)))
    : previous;
  const visibleIncoming = deleted
    ? incoming.filter(item => !deleted.has(messageId(item)))
    : incoming;
  if (!visibleIncoming.length) return visiblePrevious;

  const incomingById = new Map();
  for (const item of visibleIncoming) incomingById.set(messageId(item), item);
  const clientIds = new Set(
    [...incomingById.values()].map(item => item.metadata?.client_message_id).filter(Boolean),
  );
  const mergedById = new Map();

  for (const item of visiblePrevious) {
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
