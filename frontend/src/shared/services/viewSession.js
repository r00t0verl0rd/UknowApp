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

function readPosition(element, withAnchor = false) {
  if (!element) return null;
  const top = Math.min(MAX_SCROLL, Math.max(0, Math.round(element.scrollTop || 0)));
  const left = Math.min(MAX_SCROLL, Math.max(0, Math.round(element.scrollLeft || 0)));
  const position = { top, left };
  if (!withAnchor || top < 10) return position;
  const bounds = element.getBoundingClientRect();
  // The first visible stable row/message is more robust than a raw offset if
  // asynchronous images or responsive line breaks change element heights.
  for (const child of element.querySelectorAll("[data-view-anchor]")) {
    const row = child.getBoundingClientRect();
    if (row.bottom > bounds.top + 2 && row.top < bounds.bottom) {
      position.anchor = {
        id: child.getAttribute("data-view-anchor"),
        offset: Math.round(row.top - bounds.top),
      };
      break;
    }
  }
  return position;
}

function getContainers(root) {
  return Object.fromEntries(CONTAINERS
    .map(([selector, name]) => {
      const element = root.querySelector(selector);
      const scoped = element?.dataset?.viewScrollKey;
      return [scoped ? `${name}:${scoped}` : name, element];
    })
    .filter(([, el]) => el));
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
  let lastUserScrollIntent = 0;
  // Programmatic scroll events are isTrusted in modern browsers too. Only
  // real wheel/touch/keyboard input is allowed to cancel a pending restore.
  const onScrollIntent = event => {
    if (!event.isTrusted) return;
    // A tap/click to change a tab is not a scroll gesture. In particular it
    // must not cancel the restored position of the destination page.
    if (event.type === "keydown" &&
        !["ArrowDown", "ArrowUp", "PageDown", "PageUp", "Home", "End", " "].includes(event.key)) return;
    if (event.type === "pointermove" && !event.buttons) return;
    lastUserScrollIntent = Date.now();
  };
  let flushTimer = 0;
  let queuedScroll = {};

  const flushScroll = () => {
    if (flushTimer) win.clearTimeout(flushTimer);
    flushTimer = 0;
    if (!Object.keys(queuedScroll).length) return;
    saveScrollPositions(userId, activePage, queuedScroll);
    queuedScroll = {};
  };
  const collect = () => {
    const scrolling = doc.scrollingElement;
    const documentPosition = readPosition(scrolling, true) || { top: 0, left: 0 };
    const patch = { document: documentPosition };
    for (const [name, element] of Object.entries(getContainers(root))) {
      patch[name] = readPosition(element, true);
    }
    return patch;
  };
  const save = () => {
    if (disposed) return;
    flushScroll();
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
      const available = Math.max(0, el.scrollHeight - el.clientHeight);
      let desired = Math.max(0, saved.top);
      let anchorFound = false;
      if (saved.anchor?.id) {
        const anchor = [...el.querySelectorAll("[data-view-anchor]")]
          .find(node => node.getAttribute("data-view-anchor") === saved.anchor.id);
        if (anchor) {
          desired = Math.max(0, el.scrollTop +
            anchor.getBoundingClientRect().top - el.getBoundingClientRect().top -
            (saved.anchor.offset || 0));
          anchorFound = true;
        }
      }
      const current = Math.min(desired, available);
      if (name === "document") {
        win.scrollTo(saved.left || 0, current);
      } else {
        el.scrollTop = current;
        el.scrollLeft = saved.left || 0;
      }
      // Keep the target if rows are still loading; do not replace it with a
      // temporary clamped offset or discard an anchor before it is rendered.
      if (available + 2 >= desired && (!saved.anchor || anchorFound)) {
        delete pendingRestore[name];
      }
    }
    win.requestAnimationFrame(() => { restoring = false; });
  };
  const scheduleApply = () => {
    if (!frame) frame = win.requestAnimationFrame(apply);
  };
  const onScroll = event => {
    if (restoring || disposed || !event.isTrusted) return;
    if (Date.now() - lastUserScrollIntent > 1600) return;
    const target = event.target;
    const baseName = target === doc || target === win
      ? "document"
      : CONTAINERS.find(([selector]) => target?.matches?.(selector))?.[1];
    if (!baseName) return;
    const name = target?.dataset?.viewScrollKey
      ? `${baseName}:${target.dataset.viewScrollKey}`
      : baseName;
    userInteracted.add(name);
    delete pendingRestore[name];
    queuedScroll[name] = name === "document"
      ? { top: Math.round(win.scrollY), left: Math.round(win.scrollX) }
      : readPosition(target);
    if (!flushTimer) flushTimer = win.setTimeout(flushScroll, 90);
  };
  const onPageHide = () => save();
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
    attachObservers();
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
    const activeChatKey = viewPreference(userId, "chats.active", null);
    const relevant = Object.fromEntries(Object.entries(saved).filter(([name]) =>
      !name.startsWith("messages:") || name === `messages:${activeChatKey}`,
    ));
    pendingRestore = Object.keys(relevant).length
      ? relevant
      : { content: { top: 0, left: 0 }, document: { top: 0, left: 0 } };
    restoreDetails();
    attachObservers();
    scheduleApply();
  };
  doc.addEventListener("wheel", onScrollIntent, { capture: true, passive: true });
  doc.addEventListener("touchmove", onScrollIntent, { capture: true, passive: true });
  doc.addEventListener("pointermove", onScrollIntent, { capture: true, passive: true });
  doc.addEventListener("keydown", onScrollIntent, true);
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
      flushScroll();
      // Prior UI actions store scroll independently, including when navigation
      // came from history rather than a sidebar click.
      activePage = nextPage;
      startRestore();
    },
    dispose() {
      save();
      disposed = true;
      if (frame) win.cancelAnimationFrame(frame);
      observer.disconnect();
      resize?.disconnect();
      doc.removeEventListener("wheel", onScrollIntent, true);
      doc.removeEventListener("touchmove", onScrollIntent, true);
      doc.removeEventListener("pointermove", onScrollIntent, true);
      doc.removeEventListener("keydown", onScrollIntent, true);
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
