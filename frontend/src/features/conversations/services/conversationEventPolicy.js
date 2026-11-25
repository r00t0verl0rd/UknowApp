// Keep messages and dialog rows stable when an SSE event carries no new data.
export function hasSummaryChanges(previous, summary) {
  return Object.entries(summary).some(([key, value]) => {
    const oldValue = previous[key];
    if (Object.is(oldValue, value)) return false;
    if (!oldValue || !value || typeof oldValue !== "object" || typeof value !== "object")
      return true;
    return JSON.stringify(oldValue) !== JSON.stringify(value);
  });
}

// Read receipts can be applied locally for participants. Admin's shared
// conversation view still needs to retrieve both participants' read states.
export function requiresMessageSync(action, viewerRole, conversationType, messageStatus = null) {
  // External delivery never changes the participant's web delivery state.
  // Admin receives the changed metadata directly; old servers fall back to sync.
  if (action === "delivery") return viewerRole === "admin" && !messageStatus;
  return action !== "read" || (viewerRole === "admin" && conversationType !== "personal");
}

export function applyDeliveryStatus(rows, status, merge) {
  // A partial status must never create an unloaded or deleted bubble.
  if (!status || !rows.some(row => Number(row.id) === Number(status.id))) return rows;
  return merge(rows, [status]);
}
