import { useRef, useState } from "react";

export function useAuthState() {
  const [auth, setAuth] = useState(() => localStorage.getItem("uknowapp-auth") === "1" || sessionStorage.getItem("uknowapp-auth") === "1" ? "1" : "");
  const [theme, setTheme] = useState(() => localStorage.getItem("uknowapp-theme-v2") || "dark-soft");
  const [profile, setProfile] = useState(null);
  const [login, setLogin] = useState("");
  const [password, setPassword] = useState("");
  return { auth, setAuth, theme, setTheme, profile, setProfile, login, setLogin, password, setPassword };
}
