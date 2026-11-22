import { useCallback, useEffect, useState } from "react";

export function useSettingsState() {
  const [theme, setTheme] = useState(() => localStorage.getItem("uknowapp-theme-v2") || "dark-soft");

  useEffect(() => {
    localStorage.setItem("uknowapp-theme-v2", theme);
    document.documentElement.dataset.theme = theme;
    // Цвет прозрачных панелей мобильного Safari совпадает с общим фоном.
    document.querySelector('meta[name="theme-color"]')?.setAttribute(
      "content", theme === "dark-soft" ? "#202938" : "#faf8fd",
    );
  }, [theme]);

  const toggleTheme = useCallback(() => {
    setTheme(current => current === "dark-soft" ? "light" : "dark-soft");
  }, []);

  return { theme, toggleTheme };
}
