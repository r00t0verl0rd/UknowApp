import LogOut from "lucide-react/dist/esm/icons/log-out.js";
import Moon from "lucide-react/dist/esm/icons/moon.js";
import Sun from "lucide-react/dist/esm/icons/sun.js";
import Info from "lucide-react/dist/esm/icons/info.js";
import { useEffect, useState } from "react";
import Button from "../shared/components/Button.jsx";
import Modal from "../shared/components/Modal.jsx";
import IconButton from "../shared/components/IconButton.jsx";

// Одна разметка и один источник состояния для всех пунктов меню.
function SidebarControl({ icon: Icon, children, current = false, className = "", onClick }) {
  return <button
    type="button"
    className={["ui-menu-control", className].filter(Boolean).join(" ")}
    aria-current={current ? "page" : undefined}
    onClick={onClick}
  >
    <Icon size={18} aria-hidden="true" />{children}
  </button>;
}

export default function WorkspaceLayout({
  role, profile, label, navigation, page, setPage, theme, toggleTheme,
  pushToggle, signOut, children,
}) {
  const additionalItem = role === "admin" ? navigation.find(item => item.page === "additional") : null;
  const [showSchoolLabel, setShowSchoolLabel] = useState(() => window.matchMedia("(min-width: 1025px)").matches);
  const [showSignOutConfirm, setShowSignOutConfirm] = useState(false);
  const [signingOut, setSigningOut] = useState(false);

  const confirmSignOut = async () => {
    if (signingOut) return;
    setSigningOut(true);
    await signOut();
  };

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
        {navigation.filter(item => item.page !== "additional").map(item =>
          <SidebarControl key={item.page} icon={item.icon} current={page === item.page}
            onClick={() => setPage(item.page)}>{item.label}</SidebarControl>
        )}
      </nav>
      <div className="sidebar-bottom">
        {additionalItem && <SidebarControl icon={Info} className="desktop-admin-extra"
          current={page === additionalItem.page} onClick={() => setPage(additionalItem.page)}>
          {additionalItem.label}
        </SidebarControl>}
        <SidebarControl icon={LogOut} className="desktop-sidebar-logout" onClick={() => setShowSignOutConfirm(true)}>
          Выход
        </SidebarControl>
        <div className="mobile-quick-actions">
          {pushToggle}{themeToggle}
          <IconButton onClick={() => setShowSignOutConfirm(true)} title="Выйти" aria-label="Выйти"><LogOut/></IconButton>
        </div>
      </div>
    </aside>
    <main className="main chats-main">
      <header className="topbar">
        <small className="topbar-user">{profile.full_name}</small>
        <div className="topbar-actions">{pushToggle}{themeToggle}</div>
      </header>
      <div className={"content workspace-content" + (page === "additional" ? " page-additional" : "")}>
        {children}
      </div>
    </main>
    {showSignOutConfirm && <Modal
      onClose={() => setShowSignOutConfirm(false)}
      closeOnBackdrop={!signingOut}
      className="confirm-delete-modal"
      role="alertdialog"
      labelledBy="sign-out-title"
      describedBy="sign-out-description"
    >
      <div className="modal-head">
        <div><div className="eyebrow">ЗАВЕРШЕНИЕ СЕАНСА</div><h2 id="sign-out-title">Выйти из аккаунта?</h2></div>
      </div>
      <p className="hint" id="sign-out-description">Вы действительно хотите выйти из аккаунта?</p>
      <div className="modal-actions">
        <Button variant="ghost" onClick={() => setShowSignOutConfirm(false)} disabled={signingOut}>Нет</Button>
        <Button variant="primary" onClick={confirmSignOut} disabled={signingOut}>{signingOut ? "Выходим…" : "Да"}</Button>
      </div>
    </Modal>}
  </div>;
}
