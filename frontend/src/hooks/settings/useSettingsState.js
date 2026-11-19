import { useState } from "react";

export function useSettingsState() {
  const [theme, setTheme] = useState(() => localStorage.getItem("uknowapp-theme-v2") || "dark-soft");
  return { theme, setTheme };
}
