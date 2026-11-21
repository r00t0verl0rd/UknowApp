import ChevronRight from "lucide-react/dist/esm/icons/chevron-right.js";
import Moon from "lucide-react/dist/esm/icons/moon.js";
import Sun from "lucide-react/dist/esm/icons/sun.js";
import Button from "../../shared/components/Button.jsx";

export default function LoginPage({ theme, toggleTheme, signIn, login, setLogin, password, setPassword, error }) {
  return (
    <div className="login-screen">
        <div className="login-card">
          <button type="button" className="theme-toggle login-theme-toggle" onClick={toggleTheme} title={theme === "dark-soft" ? "Светлая тема" : "Тёмная soft-тема"} aria-label={theme === "dark-soft" ? "Включить светлую тему" : "Включить тёмную soft-тему"}>
            {theme === "dark-soft" ? <Sun size={17}/> : <Moon size={17}/>}
          </button>
          <img src="/logo.png" alt="UknowApp" className="login-logo" />
          <h1>UknowApp</h1>
          <form onSubmit={signIn} className="stack">
            <label><input value={login} onChange={e => setLogin(e.target.value)} autoComplete="username" placeholder="Логин" aria-label="Логин" /></label>
            <label><input type="password" value={password} onChange={e => setPassword(e.target.value)} autoComplete="current-password" placeholder="Пароль" aria-label="Пароль" /></label>
            {error && <div className="alert">{error}</div>}
            <Button variant="primary" type="submit">Войти <ChevronRight size={17}/></Button>
          </form>
        </div>
      </div>
  );
}
