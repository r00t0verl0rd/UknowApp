// Unified mobile visual viewport handling for login, every workspace and native dialogs.
// The layout viewport on iOS Safari can remain unchanged while the keyboard is visible.
export function installViewportEnvironment(win = window, doc = document) {
  const root = doc.documentElement;
  const viewport = win.visualViewport;
  let animationFrame = 0;
  let previousHeight = -1;
  let previousTop = NaN;
  let baselineHeight = Math.max(win.innerHeight, viewport?.height || 0);
  let keyboardOpen = false;

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
    const mobile = win.matchMedia("(max-width: 1024px)").matches;
    if (!focused || !mobile) baselineHeight = Math.max(win.innerHeight, height);
    else baselineHeight = Math.max(baselineHeight, height);
    const open = mobile && focused && (!viewport || viewport.scale <= 1.1) &&
      baselineHeight - height >= 120;

    if (open !== keyboardOpen) {
      keyboardOpen = open;
      if (open) root.setAttribute("data-app-keyboard", "open");
      else root.removeAttribute("data-app-keyboard");
      // Existing chat/layout styles continue to use this shared state.
      if (open) root.setAttribute("data-workspace-keyboard", "open");
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

    // Native scrollIntoView is necessary for long forms inside a modal or
    // login card; chat composer positioning is handled by workspace CSS.
    if (open && doc.activeElement?.closest?.(".login-screen, dialog.native-dialog")) {
      const field = doc.activeElement;
      const bounds = field.getBoundingClientRect();
      if (bounds.bottom > top + height - 12 || bounds.top < top + 12) {
        field.scrollIntoView({ block: "nearest", inline: "nearest", behavior: "auto" });
      }
    }
  };
  const schedule = () => {
    if (!animationFrame) animationFrame = win.requestAnimationFrame(measure);
  };
  const onOrientationChange = () => {
    baselineHeight = Math.max(win.innerHeight, viewport?.height || 0);
    schedule();
  };

  measure();
  viewport?.addEventListener("resize", schedule);
  viewport?.addEventListener("scroll", schedule, { passive: true });
  win.addEventListener("resize", schedule);
  win.addEventListener("orientationchange", onOrientationChange);
  win.addEventListener("pageshow", schedule);
  doc.addEventListener("focusin", schedule);
  doc.addEventListener("focusout", schedule);

  return () => {
    if (animationFrame) win.cancelAnimationFrame(animationFrame);
    viewport?.removeEventListener("resize", schedule);
    viewport?.removeEventListener("scroll", schedule);
    win.removeEventListener("resize", schedule);
    win.removeEventListener("orientationchange", onOrientationChange);
    win.removeEventListener("pageshow", schedule);
    doc.removeEventListener("focusin", schedule);
    doc.removeEventListener("focusout", schedule);
    root.removeAttribute("data-app-keyboard");
    root.removeAttribute("data-workspace-keyboard");
    for (const key of [
      "--app-viewport-height", "--app-viewport-top",
      "--workspace-viewport-height", "--workspace-viewport-top",
    ]) root.style.removeProperty(key);
  };
}
