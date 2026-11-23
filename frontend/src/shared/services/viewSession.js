// Session-only, per-user view state. Never store access tokens, passwords or message bodies.
const VERSION = "uknowapp-view-v1";
const MAX_STORED_PAGES = 12;
const MAX_SCROLL = 10_000_000;

function key(userId) {
  return userId == null ? "" : `${VERSION}:${encodeURIComponent(String(userId))}`;
}

export function readViewState(userId) {
  if (!key(userId)) return {};
  try {
    const value = JSON.parse(sessionStorage.getItem(key(userId)) || "{}");
    return value && typeof value === "object" && !Array.isArray(value) ? value : {};
  } catch {
    return {};
  }
}

export function updateViewState(userId, updater) {
  if (!key(userId)) return;
  try {
    const next = updater(readViewState(userId));
    if (!next || typeof next !== "object") return;
    sessionStorage.setItem(key(userId), JSON.stringify(next));
  } catch {
    // Private browsing / storage quota must never break the application.
  }
}

export function viewPreference(userId, name, fallback) {
  const value = readViewState(userId).preferences?.[name];
  return value === undefined ? fallback : value;
}

export function saveViewPreference(userId, name, value) {
  updateViewState(userId, state => ({
    ...state,
    preferences: { ...(state.preferences || {}), [name]: value },
  }));
}

export function readScrollPositions(userId, page) {
  return readViewState(userId).pages?.[page]?.scroll || {};
}

export function saveScrollPositions(userId, page, patch) {
  updateViewState(userId, state => {
    const pages = { ...(state.pages || {}) };
    pages[page] = {
      ...pages[page],
      scroll: { ...(pages[page]?.scroll || {}), ...patch },
    };
    // Bound storage even if new sections are added later.
    for (const old of Object.keys(pages).slice(0, Math.max(0, Object.keys(pages).length - MAX_STORED_PAGES))) {
      if (old !== page) delete pages[old];
    }
    return { ...state, pages };
  });
}

export function clearViewState(userId) {
  try {
    sessionStorage.removeItem(key(userId));
  } catch {
    // Storage may be unavailable in private mode.
  }
}

const CONTAINERS = [
  [".workspace-content", "content"],
  [".structure-scroll", "structure"],
  [".user-list", "users"],
  [".chat-items", "chat-list"],
  [".messages", "messages"],
  [".sidebar nav", "navigation"],
];

function readPosition(element) {
  if (!element) return null;
  const top = Math.min(MAX_SCROLL, Math.max(0, Math.round(element.scrollTop || 0)));
  const left = Math.min(MAX_SCROLL, Math.max(0, Math.round(element.scrollLeft || 0)));
  return { top, left };
}

function getContainers(root) {
  return Object.fromEntries(CONTAINERS.map(([selector, name]) => [name, root.querySelector(selector)]).filter(([, el]) => el));
}

export function installViewRestoration({ root, userId, page }) {
  if (!root || userId == null) return () => {};
  const doc = root.ownerDocument;
  const win = doc.defaultView;
  const previousRestoration = win.history.scrollRestoration;
  win.history.scrollRestoration = "manual";
  let activePage = page;
  let frame = 0;
  let disposed = false;
  let pendingRestore = {};
  let restoring = false;
  let userInteracted = new Set();

  const collect = () => {
    const patch = { document: { top: win.scrollY || doc.scrollingElement?.scrollTop || 0, left: win.scrollX || 0 } };
    for (const [name, element] of Object.entries(getContainers(root))) patch[name] = readPosition(element);
    return patch;
  };
  const save = () => {
    if (disposed) return;
    const patch = collect();
    // Empty placeholders must not overwrite a pending scroll restoration.
    for (const [name, saved] of Object.entries(pendingRestore)) {
      if (!userInteracted.has(name)) patch[name] = saved;
    }
    saveScrollPositions(userId, activePage, patch);
  };
  const apply = () => {
    frame = 0;
    if (disposed || !root.isConnected) return;
    restoring = true;
    const nodes = getContainers(root);
    for (const [name, saved] of Object.entries(pendingRestore)) {
      if (userInteracted.has(name)) {
        delete pendingRestore[name];
        continue;
      }
      const el = name === "document" ? doc.scrollingElement : nodes[name];
      if (!el || !saved || !Number.isFinite(saved.top)) continue;
      const desired = Math.max(0, saved.top);
      const available = Math.max(0, el.scrollHeight - el.clientHeight);
      const current = Math.min(desired, available);
      if (name === "document") {
        win.scrollTo(saved.left || 0, current);
      } else {
        el.scrollTop = current;
        el.scrollLeft = saved.left || 0;
      }
      // When data is still streaming in, keep the original target. Never
      // rewrite it with the clamped initial position (usually 0).
      if (available + 2 >= desired) delete pendingRestore[name];
    }
    win.requestAnimationFrame(() => { restoring = false; });
  };
  const scheduleApply = () => {
    if (!frame) frame = win.requestAnimationFrame(apply);
  };
  const onScroll = event => {
    if (restoring || disposed || !event.isTrusted) return;
    const target = event.target;
    const name = target === doc || target === win
      ? "document"
      : CONTAINERS.find(([selector]) => target?.matches?.(selector))?.[1];
    if (!name) return;
    userInteracted.add(name);
    delete pendingRestore[name];
    saveScrollPositions(userId, activePage, {
      [name]: name === "document"
        ? { top: Math.round(win.scrollY), left: Math.round(win.scrollX) }
        : readPosition(target),
    });
  };
  const onPageHide = () => {
    if (!restoring) save();
  };
  const onToggle = event => {
    if (event.target?.tagName !== "DETAILS" || !event.isTrusted) return;
    const details = [...root.querySelectorAll(".workspace-content details")];
    const index = details.indexOf(event.target);
    if (index < 0) return;
    const id = `expanded:${index}`;
    saveViewPreference(userId, `${activePage}:${id}`, event.target.open);
  };
  const restoreDetails = () => {
    const details = root.querySelectorAll(".workspace-content details");
    details.forEach((element, index) => {
      const expected = viewPreference(userId, `${activePage}:expanded:${index}`, null);
      if (expected !== null && element.open !== expected) element.open = expected;
    });
  };

  const observer = new MutationObserver(() => {
    restoreDetails();
    if (Object.keys(pendingRestore).length) scheduleApply();
  });
  observer.observe(root, { childList: true, subtree: true });
  const resize = typeof ResizeObserver === "function"
    ? new ResizeObserver(() => {
        if (Object.keys(pendingRestore).length) scheduleApply();
      })
    : null;
  resize?.observe(root);
  const attachObservers = () => {
    for (const element of Object.values(getContainers(root))) resize?.observe(element);
  };
  const startRestore = () => {
    userInteracted = new Set();
    const saved = readScrollPositions(userId, activePage);
    pendingRestore = Object.keys(saved).length
      ? { ...saved }
      : { content: { top: 0, left: 0 }, document: { top: 0, left: 0 } };
    restoreDetails();
    attachObservers();
    scheduleApply();
  };
  doc.addEventListener("scroll", onScroll, true);
  win.addEventListener("scroll", onScroll, { passive: true });
  doc.addEventListener("toggle", onToggle, true);
  win.addEventListener("pagehide", onPageHide);
  win.addEventListener("beforeunload", onPageHide);
  const onResize = () => { attachObservers(); scheduleApply(); };
  win.addEventListener("resize", onResize);
  startRestore();
  return {
    capture: save,
    changePage(nextPage) {
      if (nextPage === activePage) return;
      // Prior UI actions store scroll independently, including when navigation
      // came from history rather than a sidebar click.
      activePage = nextPage;
      startRestore();
    },
    dispose() {
      if (!restoring) save();
      disposed = true;
      if (frame) win.cancelAnimationFrame(frame);
      observer.disconnect();
      resize?.disconnect();
      doc.removeEventListener("scroll", onScroll, true);
      doc.removeEventListener("toggle", onToggle, true);
      win.removeEventListener("scroll", onScroll);
      win.removeEventListener("pagehide", onPageHide);
      win.removeEventListener("beforeunload", onPageHide);
      win.removeEventListener("resize", onResize);
      win.history.scrollRestoration = previousRestoration;
    },
  };
}
