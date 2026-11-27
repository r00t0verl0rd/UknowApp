import { apiUrl, fetchApi, request } from "../../../shared/services/api.js";

// Статистика различает истёкшую сессию, недоступный сервер и неверный ответ.
export async function getAdminDataStats() {
  let response;
  try {
    response = await fetchApi("/api/admin/data/stats");
  } catch {
    throw Object.assign(new Error("Нет связи с сервером. Проверьте подключение и повторите запрос."), {
      status: 0,
    });
  }
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    let message;
    if (response.status === 401 || response.status === 403) {
      message = "Сессия администратора недействительна. Для просмотра статистики войдите повторно.";
    } else if (response.status >= 500) {
      message = "Сервер не смог получить статистику (HTTP " + response.status +
        "). Повторите запрос. Если ошибка сохраняется, проверьте журнал backend.";
    } else {
      message = typeof data?.detail === "string"
        ? data.detail
        : "Не удалось получить статистику (HTTP " + response.status + ").";
    }
    throw Object.assign(new Error(message), { status: response.status });
  }
  if (!data || typeof data.users !== "number" || typeof data.database_bytes !== "number") {
    throw Object.assign(new Error("Сервер вернул неполную статистику. Повторите запрос."), {
      status: 502,
    });
  }
  return data;
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
