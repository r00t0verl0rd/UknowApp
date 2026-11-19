import { useRef, useState } from "react";

export function useAuthState() {
  const [auth, setAuth] = useState(() => localStorage.getItem("uknowapp-auth") === "1" || sessionStorage.getItem("uknowapp-auth") === "1" ? "1" : "");
  const [profile, setProfile] = useState(null);
  const [login, setLogin] = useState("");
  const [password, setPassword] = useState("");
  return { auth, setAuth, profile, setProfile, login, setLogin, password, setPassword };
}
