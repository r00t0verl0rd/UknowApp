export function mergeInboxSnapshot(snapshot, current, preserveIds) {
  if (!current.length || preserveIds?.size === 0) return snapshot;
  const shouldPreserve = preserveIds || new Set(current.map(item => Number(item.id)));
  const liveById = new Map(
    current.filter(item => shouldPreserve.has(Number(item.id)))
      .map(item => [Number(item.id), item]),
  );
  if (!liveById.size) return snapshot;
  const merged = snapshot.map(item => liveById.get(Number(item.id)) || item);
  const snapshotIds = new Set(snapshot.map(item => Number(item.id)));
  for (const item of liveById.values()) {
    if (!snapshotIds.has(Number(item.id))) merged.push(item);
  }
  return merged;
}
