// Long-lived, per-account UI preference. Store only the sort key, never user
// details or credentials. Unavailable browser storage must not block the UI.
const KEY_PREFIX = "uknowapp-user-sort-v1:";
const SORT_OPTIONS = new Set(["name-asc", "name-desc", "teachers", "students"]);

function preferenceKey(userId) {
  return userId == null ? null : KEY_PREFIX + encodeURIComponent(String(userId));
}

export function readUserSortPreference(userId, fallback = "students", storage) {
  const safeFallback = SORT_OPTIONS.has(fallback) ? fallback : "students";
  const key = preferenceKey(userId);
  if (!key) return safeFallback;
  try {
    const saved = (storage ?? window.localStorage).getItem(key);
    return SORT_OPTIONS.has(saved) ? saved : safeFallback;
  } catch {
    return safeFallback;
  }
}

export function saveUserSortPreference(userId, value, storage) {
  const key = preferenceKey(userId);
  if (!key || !SORT_OPTIONS.has(value)) return;
  try {
    (storage ?? window.localStorage).setItem(key, value);
  } catch {
    // A blocked/private browser store only affects persistence, not sorting.
  }
}
