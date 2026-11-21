export function mergeInboxSnapshot(snapshot, current) {
  if (!current.length) return snapshot;
  const liveById = new Map(current.map(item => [Number(item.id), item]));
  const merged = snapshot.map(item => liveById.get(Number(item.id)) || item);
  const snapshotIds = new Set(snapshot.map(item => Number(item.id)));
  for (const item of current) {
    if (!snapshotIds.has(Number(item.id))) merged.push(item);
  }
  return merged;
}
