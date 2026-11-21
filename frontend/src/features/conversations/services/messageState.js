export function mergeConversationMessages(previous, incoming) {
  if (!incoming.length) return previous;

  const clientIds = new Set(
    incoming.map(item => item.metadata?.client_message_id).filter(Boolean),
  );
  const incomingById = new Map(incoming.map(item => [String(item.id), item]));
  const merged = previous
    .filter(item => !clientIds.has(item.metadata?.client_message_id))
    .map(item => {
      const update = incomingById.get(String(item.id));
      if (!update) return item;

      const result = {
        ...item,
        ...update,
        metadata: { ...(item.metadata || {}), ...(update.metadata || {}) },
      };

      // Read receipts and delivery cannot move backwards because an older
      // in-flight response arrived after a newer SSE event.
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
    ...incoming.filter(item => !known.has(String(item.id))),
  ];
}
