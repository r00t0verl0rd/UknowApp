const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "";

export function createApiClient() {
  return async function request(path, options = {}) {
    const response = await fetch(API_BASE_URL + path, {
      ...options,
      credentials: "include",
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    });
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
  };
}
