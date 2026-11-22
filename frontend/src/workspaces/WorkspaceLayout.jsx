import { For } from "solid-js";
import { dynamic } from "@solidjs/web";
import { createSignal, createEffect } from "solid-js";
import {
  IconLogOut as LogOut,
  IconMoon as Moon,
  IconSun as Sun,
  IconInfo as Info,
} from "../shared/components/Icons.jsx";
import Button from "../shared/components/Button.jsx";
import Modal from "../shared/components/Modal.jsx";
import IconButton from "../shared/components/IconButton.jsx";

// Одна разметка и один источник состояния для всех пунктов меню.
function SidebarControl(options) {
  const Icon = dynamic(() => options.icon);
  return (
    <button
      type="button"
      class={["ui-menu-control", options.class ?? ""].filter(Boolean).join(" ")}
      aria-current={(options.current ?? false) ? "page" : undefined}
      onClick={options.onClick}
    >
      <Icon size={18} aria-hidden="true" />
      {options.children}
    </button>
  );
}
export default function WorkspaceLayout(options) {
  const additionalItem = () =>
    options.role === "admin" ? options.navigation.find((item) => item.page === "additional") : null;
  const [showSignOutConfirm, setShowSignOutConfirm] = createSignal(false);
  const [signingOut, setSigningOut] = createSignal(false);
  let contentRef = null;
  let sidebarRef = null;
  let shellRef = null;
  createEffect(
    () => [options.page],
    () => {
      contentRef.scrollTop = 0;
      // В мобильном Safari нативный document — единственный скроллер.
      if (window.matchMedia("(max-width: 1024px) and (display-mode: browser)").matches) {
        window.scrollTo(0, 0);
      }
    },
  );

  // Размер visualViewport используется для Desktop/PWA и открытого диалога.
  // В Safari списки прокручиваются документом, чтобы WebKit рисовал их под toolbar.
  createEffect(
    () => [],
    () => {
      const root = document.documentElement;
      const viewport = window.visualViewport;
      if (!viewport) return undefined;
      const measureViewport = () => {
        const height = Math.round(viewport.height);
        const top = Math.round(viewport.offsetTop);
        if (!Number.isFinite(height) || height <= 0) return;
        root.style.setProperty("--workspace-viewport-height", `${height}px`);
        root.style.setProperty("--workspace-viewport-top", `${top}px`);
      };
      measureViewport();
      viewport.addEventListener("resize", measureViewport);
      viewport.addEventListener("scroll", measureViewport);
      window.addEventListener("resize", measureViewport);
      window.addEventListener("orientationchange", measureViewport);
      window.addEventListener("pageshow", measureViewport);
      return () => {
        viewport.removeEventListener("resize", measureViewport);
        viewport.removeEventListener("scroll", measureViewport);
        window.removeEventListener("resize", measureViewport);
        window.removeEventListener("orientationchange", measureViewport);
        window.removeEventListener("pageshow", measureViewport);
        root.style.removeProperty("--workspace-viewport-height");
        root.style.removeProperty("--workspace-viewport-top");
      };
    },
  );

  // Высота мобильной навигации может измениться при переносе/масштабе текста.
  // ResizeObserver синхронизирует отступ контента с реальным размером меню.
  createEffect(
    () => [],
    () => {
      const sidebar = sidebarRef;
      const shell = shellRef;
      if (!sidebar || !shell) return undefined;
      const syncSidebarHeight = () => {
        const height = Math.ceil(sidebar.getBoundingClientRect().height);
        if (height > 0) shell.style.setProperty("--workspace-sidebar-height", `${height}px`);
      };
      syncSidebarHeight();
      const observer = typeof ResizeObserver === "function" ? new ResizeObserver(syncSidebarHeight) : null;
      observer?.observe(sidebar);
      window.addEventListener("resize", syncSidebarHeight);
      return () => {
        observer?.disconnect();
        window.removeEventListener("resize", syncSidebarHeight);
        shell.style.removeProperty("--workspace-sidebar-height");
      };
    },
  );
  const confirmSignOut = async () => {
    if (signingOut()) return;
    setSigningOut(true);
    await options.signOut();
  };
  const themeToggle = () => (
    <IconButton
      class="theme-toggle"
      onClick={options.toggleTheme}
      title={options.theme === "dark-soft" ? "Светлая тема" : "Тёмная soft-тема"}
      aria-label={options.theme === "dark-soft" ? "Включить светлую тему" : "Включить тёмную soft-тему"}
    >
      {options.theme === "dark-soft" ? <Sun size={17} /> : <Moon size={17} />}
    </IconButton>
  );
  return (
    <div ref={shellRef} class={`shell workspace-shell workspace-${options.role}`}>
      <aside ref={sidebarRef} class="sidebar">
        <div class="brand">
          <img src="/logo-main.svg" alt="" />
          <span>
            Uknow<span>App</span>
          </span>
        </div>
        <div class="school-label">{options.label}</div>
        <nav aria-label="Основная навигация">
          <For each={options.navigation.filter((item) => item.page !== "additional")}>
            {(item) => (
              <SidebarControl
                icon={item.icon}
                current={options.page === item.page}
                onClick={() => options.setPage(item.page)}
              >
                {item.label}
              </SidebarControl>
            )}
          </For>
        </nav>
        <div class="sidebar-bottom">
          {additionalItem() && (
            <SidebarControl
              icon={Info}
              class="desktop-admin-extra"
              current={options.page === additionalItem().page}
              onClick={() => options.setPage(additionalItem().page)}
            >
              {additionalItem().label}
            </SidebarControl>
          )}
          <SidebarControl
            icon={LogOut}
            class="desktop-sidebar-logout"
            onClick={() => setShowSignOutConfirm(true)}
          >
            Выход
          </SidebarControl>
          <div class="mobile-quick-actions">
            {options.pushToggle}
            {themeToggle()}
            <IconButton onClick={() => setShowSignOutConfirm(true)} title="Выйти" aria-label="Выйти">
              <LogOut />
            </IconButton>
          </div>
        </div>
      </aside>
      <main class="content">
        <header class="topbar">
          <small class="topbar-user">{options.profile.full_name}</small>
          <div class="topbar-actions">
            {options.pushToggle}
            {themeToggle()}
          </div>
        </header>
        <div
          ref={contentRef}
          tabIndex={0}
          class={"workspace-content" + (options.page === "additional" ? " page-additional" : "")}
        >
          {options.children}
        </div>
      </main>
      {showSignOutConfirm() && (
        <Modal
          onClose={() => setShowSignOutConfirm(false)}
          closeOnBackdrop={!signingOut()}
          class="confirm-delete-modal"
          role="alertdialog"
          labelledBy="sign-out-title"
          describedBy="sign-out-description"
        >
          <div class="modal-head">
            <div>
              <div class="eyebrow">ЗАВЕРШЕНИЕ СЕАНСА</div>
              <h2 id="sign-out-title">Выйти из аккаунта?</h2>
            </div>
          </div>
          <p class="hint" id="sign-out-description">
            Вы действительно хотите выйти из аккаунта?
          </p>
          <div class="modal-actions">
            <Button variant="ghost" onClick={() => setShowSignOutConfirm(false)} disabled={signingOut()}>
              Нет
            </Button>
            <Button variant="primary" onClick={confirmSignOut} disabled={signingOut()}>
              {signingOut() ? "Выходим…" : "Да"}
            </Button>
          </div>
        </Modal>
      )}
    </div>
  );
}
