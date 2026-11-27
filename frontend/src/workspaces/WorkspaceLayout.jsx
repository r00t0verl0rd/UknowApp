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
import ConfirmDialog from "../shared/components/ConfirmDialog.jsx";
import IconButton from "../shared/components/IconButton.jsx";
import { viewAccountKey, installViewRestoration } from "../shared/services/viewSession.js";

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
  let viewMemory = null;
// Единое управление прокруткой и её восстановлением во всех разделах.
  createEffect(
    () => [viewAccountKey(options.profile)],
    ([id]) => {
      viewMemory?.dispose();
      viewMemory = id == null ? null : installViewRestoration({
        root: shellRef, userId: id, page: options.page,
      });
      return () => {
        viewMemory?.dispose();
        viewMemory = null;
      };
    },
  );
  createEffect(
    () => [options.page],
    ([page]) => viewMemory?.changePage(page),
  );
  const navigate = page => {
    viewMemory?.capture();
    // Меняем область сохранения до следующего действия навигации.
    viewMemory?.changePage(page);
    options.setPage(page);
  };

  // ResizeObserver уже сообщает высоту: не пересчитываем разметку на каждом
  // window.resize и не обновляем отступ, когда ширина меняется без переноса меню.
  createEffect(
    () => [],
    () => {
      const sidebar = sidebarRef;
      const shell = shellRef;
      if (!sidebar || !shell) return undefined;
      const mobile = window.matchMedia("(max-width: 1024px)");
      let previousHeight = -1;
      const syncSidebarHeight = (entry) => {
        if (!mobile.matches) return;
        const box = entry?.borderBoxSize;
        const measuredHeight = (Array.isArray(box) ? box[0]?.blockSize : box?.blockSize)
          ?? sidebar.getBoundingClientRect().height;
        const height = Math.ceil(measuredHeight);
        if (height > 0 && height !== previousHeight) {
          shell.style.setProperty("--workspace-sidebar-height", `${height}px`);
          previousHeight = height;
        }
      };
      const observer = typeof ResizeObserver === "function"
        ? new ResizeObserver(([entry]) => syncSidebarHeight(entry))
        : null;
      const onBreakpointChange = () => {
        if (mobile.matches) {
          observer?.observe(sidebar);
          syncSidebarHeight();
        } else {
          // На десктопе наблюдение не нужно: sidebar меняет ширину на каждом пикселе.
          observer?.unobserve(sidebar);
        }
      };
      mobile.addEventListener("change", onBreakpointChange);
      if (!observer) window.addEventListener("resize", onBreakpointChange);
      onBreakpointChange();
      return () => {
        observer?.disconnect();
        mobile.removeEventListener("change", onBreakpointChange);
        if (!observer) window.removeEventListener("resize", onBreakpointChange);
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
    <div ref={shellRef} class="shell workspace-shell" data-workspace-page={options.page}>
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
                onClick={() => navigate(item.page)}
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
              onClick={() => navigate(additionalItem().page)}
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
        <ConfirmDialog
          eyebrow="ЗАВЕРШЕНИЕ СЕАНСА"
          title="Выйти из аккаунта?"
          titleId="sign-out-title"
          describedBy="sign-out-description"
          dismissible={false}
          busy={signingOut()}
          tone="primary"
          cancelLabel="Нет"
          confirmLabel="Да"
          busyLabel="Выходим…"
          onClose={() => setShowSignOutConfirm(false)}
          onConfirm={confirmSignOut}
        >
          Вы действительно хотите выйти из аккаунта?
        </ConfirmDialog>
      )}
    </div>
  );
}
