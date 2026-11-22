import { createSignal, createEffect } from "solid-js";
export function createSettingsState() {
  const [theme, setTheme] = createSignal(localStorage.getItem("uknowapp-theme-v2") || "dark-soft");
  createEffect(
    () => [theme()],
    () => {
      localStorage.setItem("uknowapp-theme-v2", theme());
      document.documentElement.dataset.theme = theme();
      // Цвет прозрачных панелей мобильного Safari совпадает с общим фоном.
      document
        .querySelector('meta[name="theme-color"]')
        ?.setAttribute("content", theme() === "dark-soft" ? "#202938" : "#faf8fd");
    },
  );
  const toggleTheme = () => {
    setTheme((current) => (current === "dark-soft" ? "light" : "dark-soft"));
  };
  return {
    get theme() {
      return theme();
    },
    toggleTheme,
  };
}
