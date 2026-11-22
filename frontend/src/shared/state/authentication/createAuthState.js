import { createSignal } from "solid-js";
export function createAuthState() {
  const [auth, setAuth] = createSignal(
    localStorage.getItem("uknowapp-auth") === "1" || sessionStorage.getItem("uknowapp-auth") === "1"
      ? "1"
      : "",
  );
  const [profile, setProfile] = createSignal(null);
  const [login, setLogin] = createSignal("");
  const [password, setPassword] = createSignal("");
  return {
    get auth() {
      return auth();
    },
    setAuth,
    get profile() {
      return profile();
    },
    setProfile,
    get login() {
      return login();
    },
    setLogin,
    get password() {
      return password();
    },
    setPassword,
  };
}
