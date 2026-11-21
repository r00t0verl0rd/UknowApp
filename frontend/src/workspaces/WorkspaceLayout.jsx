import LogOut from "lucide-react/dist/esm/icons/log-out.js";
import Moon from "lucide-react/dist/esm/icons/moon.js";
import Sun from "lucide-react/dist/esm/icons/sun.js";
import X from "lucide-react/dist/esm/icons/x.js";
import Info from "lucide-react/dist/esm/icons/info.js";
import { useEffect, useState } from "react";
import AppToast from "../shared/components/AppToast.jsx";
import IconButton from "../shared/components/IconButton.jsx";

export default function WorkspaceLayout({
  role, profile, label, navigation, page, setPage, theme, toggleTheme,
  pushToggle, signOut, error, setError, toast, children,
}) {
  const additionalItem = role === "admin" ? navigation.find(item => item.page === "additional") : null;
  const [showSchoolLabel, setShowSchoolLabel] = useState(() => window.matchMedia("(min-width: 1025px)").matches);

  useEffect(() => {
    const media = window.matchMedia("(min-width: 1025px)");
    const update = event => setShowSchoolLabel(event.matches);
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);

  const themeToggle = (
    <IconButton className="theme-toggle" onClick={toggleTheme}
      title={theme === "dark-soft" ? "Светлая тема" : "Тёмная soft-тема"}
      aria-label={theme === "dark-soft" ? "Включить светлую тему" : "Включить тёмную soft-тему"}>
      {theme === "dark-soft" ? <Sun size={17}/> : <Moon size={17}/>}
    </IconButton>
  );

  return <div className={`shell chats-shell workspace-shell workspace-${role}`}>
    <aside className="sidebar">
      <div className="brand"><img src="/logo.png" alt="" /><span>Uknow<span>App</span></span></div>
      {showSchoolLabel && <div className="school-label">{label}</div>}
      <nav aria-label="Основная навигация">
        {navigation.filter(item => item.page !== "additional").map(item => {
          const Icon = item.icon;
          return <button key={item.page} type="button"
            className={page === item.page ? "active" : ""}
            aria-current={page === item.page ? "page" : undefined}
            onClick={() => setPage(item.page)}>
            <Icon size={18}/>{item.label}
          </button>;
        })}
      </nav>
      <div className="sidebar-bottom">
        {additionalItem && <button type="button" className="logout desktop-admin-extra"
          aria-current={page === "additional" ? "page" : undefined}
          onClick={() => setPage(additionalItem.page)}>
          <Info size={18}/>{additionalItem.label}
        </button>}
        <button type="button" className="logout desktop-sidebar-logout" onClick={signOut}>
          <LogOut size={18}/>Выход
        </button>
        <div className="mobile-quick-actions">
          {pushToggle}{themeToggle}
          <button type="button" className="logout" onClick={signOut} title="Выйти" aria-label="Выйти"><LogOut/></button>
        </div>
      </div>
    </aside>
    <main className="main chats-main">
      <header className="topbar">
        <small className="topbar-user">{profile.full_name}</small>
        <div className="topbar-actions">{pushToggle}{themeToggle}</div>
      </header>
      <div className={"content workspace-content" + (page === "additional" ? " page-additional" : "")}>
        {error && <div className="alert alert-row" role="alert">{error}
          <button type="button" onClick={() => setError("")} aria-label="Закрыть"><X/></button>
        </div>}
        {children}
      </div>
    </main>
    <AppToast message={toast}/>
  </div>;
}
