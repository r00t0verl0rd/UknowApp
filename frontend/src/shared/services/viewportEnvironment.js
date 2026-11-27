// Единое позиционирование при открытой клавиатуре на мобильных устройствах.
export function installViewportEnvironment(win = window, doc = document) {
  const root = doc.documentElement;
  const viewport = win.visualViewport;
  const mobileQuery = win.matchMedia("(max-width: 1024px)");
  const browserQuery = win.matchMedia("(display-mode: browser)");
  const touchQuery = win.matchMedia("(pointer: coarse)");
  let animationFrame = 0;
  let previousHeight = -1;
  let previousTop = NaN;
  let baselineHeight = Math.max(win.innerHeight, viewport?.height || 0);
  let loginHeight = null;
  let keyboardOpen = false;
  let workspaceKeyboardOpen = false;

  const isEditorFocused = () => doc.activeElement?.matches?.(
    "textarea, input:not([type]), input:is([type='text'], [type='search'], [type='email'], " +
      "[type='password'], [type='tel'], [type='url'], [type='number']), [contenteditable='true']",
  ) ?? false;

  const measure = () => {
    animationFrame = 0;
    const height = Math.round(viewport?.height || win.innerHeight);
    const top = Math.round(viewport?.offsetTop || 0);
    if (!Number.isFinite(height) || height <= 0) return;
    const focused = isEditorFocused();
    const mobile = mobileQuery.matches;
    const inBrowser = mobile && browserQuery.matches;
    // Сохраняем высоту, пока Safari закрывает клавиатуру.
    if ((!focused && !keyboardOpen) || !mobile) baselineHeight = Math.max(win.innerHeight, height);
    else baselineHeight = Math.max(baselineHeight, height);
    const heightLoss = baselineHeight - height;
    // Защита от скачков высоты при закрытии клавиатуры.
    const open = mobile && (!viewport || viewport.scale <= 1.1) &&
      (keyboardOpen ? heightLoss >= 80 : focused && heightLoss >= 120);
    // Готовим чат до изменения viewport клавиатурой Safari.
    const prepareChat = inBrowser && focused &&
      touchQuery.matches &&
      Boolean(doc.activeElement?.closest?.(".chat-composer"));
    // При редактировании сворачиваем меню; диалоги управляют своим viewport.
    const field = doc.activeElement;
    const form = field?.closest?.(".login-screen, dialog.native-dialog");
    const workspaceEditor = focused && !form && Boolean(field.closest(".workspace-shell"));
    const workspaceOpen = prepareChat || (open && !form &&
      (workspaceEditor || (!focused && workspaceKeyboardOpen)));

    // Не меняем форму входа, пока клавиатура полностью не закрыта.
    const loginKeyboard = open && (form?.matches(".login-screen") ||
      (loginHeight !== null && field === doc.body && doc.querySelector(".login-screen")));
    const nextLoginHeight = loginKeyboard ? Math.min(loginHeight ?? height, height) : null;
    if (loginHeight !== nextLoginHeight) {
      loginHeight = nextLoginHeight;
      if (loginHeight === null) root.style.removeProperty("--login-height");
      else root.style.setProperty("--login-height", `${loginHeight}px`);
    }

    if (open !== keyboardOpen) {
      keyboardOpen = open;
      if (open) root.setAttribute("data-app-keyboard", "open");
      else root.removeAttribute("data-app-keyboard");
    }
    if (workspaceOpen !== workspaceKeyboardOpen) {
      workspaceKeyboardOpen = workspaceOpen;
      if (workspaceOpen) root.setAttribute("data-workspace-keyboard", "open");
      else root.removeAttribute("data-workspace-keyboard");
    }
    if (height !== previousHeight) {
      const value = `${height}px`;
      root.style.setProperty("--app-viewport-height", value);
      root.style.setProperty("--workspace-viewport-height", value);
      previousHeight = height;
    }
    if (top !== previousTop) {
      const value = `${top}px`;
      root.style.setProperty("--app-viewport-top", value);
      root.style.setProperty("--workspace-viewport-top", value);
      previousTop = top;
    }

    if (open && focused && form?.matches("dialog.native-dialog") && form.scrollHeight > form.clientHeight) {
      const bounds = field.getBoundingClientRect();
      const frame = form.getBoundingClientRect();
      const visibleTop = Math.max(top, frame.top + form.clientTop) + 12;
      const visibleBottom = Math.min(top + height, frame.top + form.clientTop + form.clientHeight) - 12;
      if (bounds.top < visibleTop) form.scrollTop += bounds.top - visibleTop;
      else if (bounds.bottom > visibleBottom) form.scrollTop += bounds.bottom - visibleBottom;
    }
  };
  const schedule = () => {
    if (!animationFrame) animationFrame = win.requestAnimationFrame(measure);
  };
  const onOrientationChange = () => {
    loginHeight = null;
    root.style.removeProperty("--login-height");
    baselineHeight = Math.max(win.innerHeight, viewport?.height || 0);
    schedule();
  };
  const onViewportScroll = () => {
    // При снятом фокусе обновляем layout только при изменении размера.
    if (mobileQuery.matches && browserQuery.matches &&
        !keyboardOpen && !isEditorFocused()) return;
    schedule();
  };

  measure();
  viewport?.addEventListener("resize", schedule);
  viewport?.addEventListener("scroll", onViewportScroll, { passive: true });
  win.addEventListener("resize", schedule);
  win.addEventListener("orientationchange", onOrientationChange);
  win.addEventListener("pageshow", schedule);
  doc.addEventListener("focusin", schedule);
  doc.addEventListener("focusout", schedule);

  return () => {
    if (animationFrame) win.cancelAnimationFrame(animationFrame);
    viewport?.removeEventListener("resize", schedule);
    viewport?.removeEventListener("scroll", onViewportScroll);
    win.removeEventListener("resize", schedule);
    win.removeEventListener("orientationchange", onOrientationChange);
    win.removeEventListener("pageshow", schedule);
    doc.removeEventListener("focusin", schedule);
    doc.removeEventListener("focusout", schedule);
    root.removeAttribute("data-app-keyboard");
    root.removeAttribute("data-workspace-keyboard");
    for (const key of [
      "--login-height", "--app-viewport-height", "--app-viewport-top",
      "--workspace-viewport-height", "--workspace-viewport-top",
    ]) root.style.removeProperty(key);
  };
}
