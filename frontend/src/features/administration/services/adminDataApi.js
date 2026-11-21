const API = import.meta.env.VITE_API_BASE_URL || "";

export function getAdminDataStats(request) {
  return request("/api/admin/data/stats");
}

export async function getRestoreStatus(signal) {
  const response = await fetch(API + "/api/admin/data/restore-status", {
    credentials: "include", cache: "no-store", signal,
  });
  if (response.status === 401 || response.status === 403) return { status: "login" };
  if (!response.ok) throw new Error("Сервер временно недоступен");
  return (await response.json()).restore;
}

export async function downloadAdminBackup(kind) {
  const response = await fetch(API + "/api/admin/data/" + kind, { credentials: "include" });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.detail || "Не удалось скачать файл");
  }
  return response.blob();
}

export async function uploadAdminBackup(kind, file) {
  const form = new FormData();
  form.append("file", file);
  const response = await fetch(API + "/api/admin/data/" + kind, {
    method: "POST", credentials: "include", body: form,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || "Не удалось загрузить файл");
  return data;
}

export function cleanupAdminDialogues(request, days) {
  return request("/api/admin/data/dialogues?days=" + days, { method: "DELETE" });
}
