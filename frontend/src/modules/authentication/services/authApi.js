const API = import.meta.env.VITE_API_BASE_URL || "";

export async function signInRequest(username, password) {
  const response = await fetch(API + "/api/auth/login", {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  const result = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = Array.isArray(result.detail)
      ? result.detail.map(item => item.msg || "Некорректные данные").join("; ")
      : typeof result.detail === "string" ? result.detail : "Не удалось войти";
    throw new Error(detail);
  }
  return result;
}

export function signOutRequest() {
  return fetch(API + "/api/auth/logout", { method: "POST", credentials: "include" });
}
