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

// Apply server-confirmed receipts locally, including the reader's other tabs.
export function applyReadReceipt(rows, payload, conversationType) {
  const role = payload.actor_role;
  const readAt = payload.read_at;
  if (!readAt || !["teacher", "student", "admin"].includes(role)) return rows;
  const ids = new Set((payload.message_ids || []).map(Number));
  let changed = false;
  const next = rows.map(row => {
    if (!ids.has(Number(row.id)) || row.sender_role === role) return row;
    if (conversationType === "personal") {
      if (row.panel_read_at) return row;
      changed = true;
      return { ...row, panel_read_at: readAt };
    }
    if (role === "admin") {
      if (row.admin_read_at) return row;
      changed = true;
      return { ...row, admin_read_at: readAt };
    }
    const field = role + "_read_at";
    if (row.metadata?.[field]) return row;
    const metadata = { ...row.metadata, [field]: readAt };
    const panel_read_at = row.sender_role === "admin"
      ? metadata.teacher_read_at && metadata.student_read_at || null
      : readAt;
    changed = true;
    return { ...row, metadata, panel_read_at };
  });
  return changed ? next : rows;
}
