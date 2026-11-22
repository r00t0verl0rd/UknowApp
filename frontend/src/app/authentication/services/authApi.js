import { fetchApi, request } from "../../../shared/services/api.js";

export function signInRequest(username, password) {
  return request("/api/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
}

export function signOutRequest() {
  return fetchApi("/api/auth/logout", { method: "POST" });
}
