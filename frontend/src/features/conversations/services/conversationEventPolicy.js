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
export function requiresMessageSync(action, viewerRole, conversationType) {
  return action !== "read" || (viewerRole === "admin" && conversationType !== "personal");
}
