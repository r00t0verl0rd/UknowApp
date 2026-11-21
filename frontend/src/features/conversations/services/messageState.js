const deletedByConversation = new Map();
const MAX_DELETED_IDS = 5000;

export function markConversationMessageDeleted(conversationKey, messageId) {
  if (!conversationKey || !Number.isSafeInteger(Number(messageId))) return;
  let deleted = deletedByConversation.get(conversationKey);
  if (!deleted) {
    deleted = new Set();
    deletedByConversation.set(conversationKey, deleted);
  }
  deleted.add(String(messageId));
  if (deleted.size > MAX_DELETED_IDS) {
    deleted.delete(deleted.values().next().value);
  }
}

export function mergeConversationMessages(previous, incoming, conversationKey = "") {
  const deleted = deletedByConversation.get(conversationKey);
  const visibleIncoming = deleted
    ? incoming.filter(item => !deleted.has(String(item.id)))
    : incoming;
  const visiblePrevious = deleted
    ? previous.filter(item => !deleted.has(String(item.id)))
    : previous;
  if (!visibleIncoming.length) return visiblePrevious;

  const clientIds = new Set(
    visibleIncoming.map(item => item.metadata?.client_message_id).filter(Boolean),
  );
  const incomingById = new Map(visibleIncoming.map(item => [String(item.id), item]));
  const merged = visiblePrevious
    .filter(item => !clientIds.has(item.metadata?.client_message_id))
    .map(item => {
      const update = incomingById.get(String(item.id));
      if (!update) return item;

      const result = {
        ...item,
        ...update,
        metadata: { ...(item.metadata || {}), ...(update.metadata || {}) },
      };

      if (item.panel_read_at && !update.panel_read_at) {
        result.panel_read_at = item.panel_read_at;
      }
      if (item.delivery_status === "delivered" && update.delivery_status === "pending") {
        result.delivery_status = item.delivery_status;
      }
      return result;
    });

  const known = new Set(merged.map(item => String(item.id)));
  return [
    ...merged,
    ...visibleIncoming.filter(item => !known.has(String(item.id))),
  ];
}
