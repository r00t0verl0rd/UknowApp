const API_BASE_URL = import.meta.env?.VITE_API_BASE_URL || "";

export function apiUrl(path) {
  return API_BASE_URL + path;
}

export function fetchApi(path, options = {}) {
  return fetch(apiUrl(path), { ...options, credentials: "include" });
}

export async function request(path, options = {}) {
  const headers = new Headers(options.headers);
  if (typeof options.body === "string" && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetchApi(path, { ...options, headers });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = Array.isArray(data.detail)
      ? data.detail.map(item => {
          const field = Array.isArray(item.loc) ? item.loc[item.loc.length - 1] : "";
          return (field ? field + ": " : "") + (item.msg || "Некорректное значение");
        }).join("; ")
      : (typeof data.detail === "string" ? data.detail : "Ошибка запроса");
    throw new Error(detail);
  }
  return data;
}
