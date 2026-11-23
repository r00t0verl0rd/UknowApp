// Применяем тему до запуска приложения: внешний файл разрешён строгим CSP.
try {
  const theme = localStorage.getItem("uknowapp-theme-v2") === "light" ? "light" : "dark-soft";
  document.documentElement.dataset.theme = theme;
  document.querySelector('meta[name="theme-color"]')?.setAttribute(
    "content", theme === "light" ? "#faf8fd" : "#202938",
  );
} catch {
  // Закрытое хранилище браузера не мешает загрузке приложения.
}
