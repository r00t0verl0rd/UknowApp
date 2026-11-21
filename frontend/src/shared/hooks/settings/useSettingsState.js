import { useCallback, useEffect, useState } from "react";

export function useSettingsState() {
  const [theme, setTheme] = useState(() => localStorage.getItem("uknowapp-theme-v2") || "dark-soft");

  useEffect(() => {
    localStorage.setItem("uknowapp-theme-v2", theme);
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  const toggleTheme = useCallback(() => {
    setTheme(current => current === "dark-soft" ? "light" : "dark-soft");
  }, []);

  return { theme, toggleTheme };
}
