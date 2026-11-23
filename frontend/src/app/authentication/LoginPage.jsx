import {
  IconChevronRight as ChevronRight,
  IconMoon as Moon,
  IconSun as Sun,
} from "../../shared/components/Icons.jsx";
import Button from "../../shared/components/Button.jsx";
import IconButton from "../../shared/components/IconButton.jsx";
export default function LoginPage(options) {
  return (
    <main class="login-screen">
      <section class="login-card" aria-label="Вход в UknowApp">
        <IconButton
          class="theme-toggle login-theme-toggle"
          onClick={options.toggleTheme}
          title={options.theme === "dark-soft" ? "Светлая тема" : "Тёмная soft-тема"}
          aria-label={options.theme === "dark-soft" ? "Включить светлую тему" : "Включить тёмную soft-тему"}
        >
          {options.theme === "dark-soft" ? <Sun size={17} /> : <Moon size={17} />}
        </IconButton>
        <div class="login-brand">
          <img src="/logo-main.svg" alt="" class="login-logo" />
          <h1>
            Uknow<span>App</span>
          </h1>
        </div>
        <form onSubmit={options.signIn} class="stack">
          <label>
            <input
              value={options.login}
              onInput={(e) => options.setLogin(e.target.value)}
              autoComplete="username"
              placeholder="Логин"
              aria-label="Логин"
            />
          </label>
          <label>
            <input
              type="password"
              value={options.password}
              onInput={(e) => options.setPassword(e.target.value)}
              autoComplete="current-password"
              placeholder="Пароль"
              aria-label="Пароль"
            />
          </label>
          <Button variant="primary" class="login-submit" type="submit">
            Войти <ChevronRight size={17} />
          </Button>
        </form>
      </section>
    </main>
  );
}
