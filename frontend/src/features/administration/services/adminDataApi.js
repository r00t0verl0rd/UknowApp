import { apiUrl, fetchApi, request } from "../../../shared/services/api.js";

export function getAdminDataStats(request) {
  return request("/api/admin/data/stats");
}

export async function getRestoreStatus(signal) {
  const response = await fetchApi("/api/admin/data/restore-status", {
    credentials: "include", cache: "no-store", signal,
  });
  if (response.status === 401 || response.status === 403) return { status: "login" };
  if (!response.ok) throw new Error("Сервер временно недоступен");
  return (await response.json()).restore;
}

export function adminBackupUrl(kind) {
  return apiUrl("/api/admin/data/" + kind);
}

export async function uploadAdminBackup(kind, file) {
  const form = new FormData();
  form.append("file", file);
  return request("/api/admin/data/" + kind, { method: "POST", body: form });
}

export function cleanupAdminDialogues(request, days) {
  return request("/api/admin/data/dialogues?days=" + days, { method: "DELETE" });
}
