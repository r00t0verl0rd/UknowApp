import { createEffect, createSignal } from "solid-js";
import {
  persistentViewValue,
  readScrollPositions,
  savePersistentViewValue,
  viewAccountKey,
} from "../../../shared/services/viewSession.js";

export function createMessageViewport(options, activeChatKey, openingRequest) {
  const [positionedKey, setPositionedKey] = createSignal("");
  const [showLatest, setShowLatest] = createSignal(false);
  let unreadAnchor = null;
  let capturePosition = () => {};
  let schedulePosition = () => {};
  let requestLatestScroll = () => {};
  const positionName = (key, filter) => `messages:${key}${filter === "all" ? "" : ":" + filter}`;
  const savedPosition = (key, filter) => {
    const name = positionName(key, filter);
    const accountId = viewAccountKey(options.profile);
    return persistentViewValue(accountId, name, readScrollPositions(accountId, "chats")[name]);
  };
  createEffect(
    () => [
      options.chatState.selectedChat?.id,
      options.chatState.selectedChat?.type,
      options.chatState.messageFilter,
      options.chatState.messagesViewportRef.current,
    ],
    () => {
      const history = options.chatState.messagesViewportRef.current;
      const key = activeChatKey();
      if (!history || !key) return;
      const filter = options.chatState.messageFilter;
      const name = positionName(key, filter);
      const userId = viewAccountKey(options.profile);
      const saved = savedPosition(key, filter);
      let position = saved;
      let initialized = false;
      let followBottom = false;
      let forced = false;
      let frame = 0;
      let captureTimer = 0;
      let appliedTop = null;
      const current = () => history.isConnected && history.clientHeight > 0 &&
        history.dataset.viewScrollKey === key && activeChatKey() === key &&
        options.chatState.messageFilter === filter;
      const distanceToLatest = () => Math.max(0,
        history.scrollHeight - history.scrollTop - history.clientHeight);
      const findRow = id => /^message:\d+$/.test(id || "") &&
        history.querySelector(`[data-view-anchor="${id}"]`);
      const readPosition = () => {
        const bounds = history.getBoundingClientRect();
        const rows = history.children;
        let low = 0;
        let high = rows.length;
        while (low < high) {
          const mid = (low + high) >>> 1;
          if (rows[mid].getBoundingClientRect().bottom <= bounds.top) low = mid + 1;
          else high = mid;
        }
        const row = rows[low]?.dataset.viewAnchor ? rows[low] : rows[low + 1];
        const id = row?.dataset.viewAnchor;
        if (!/^message:\d+$/.test(id || "")) return null;
        return {
          top: Math.max(0, history.scrollTop),
          bottom: followBottom,
          anchor: { id, offset: row.getBoundingClientRect().top - bounds.top },
        };
      };
      const persist = () => {
        if (initialized && position) savePersistentViewValue(userId, name, position);
      };
      const capture = () => {
        if (initialized && current()) {
          // Do not replace the stable anchor with a temporary geometry change.
          // Scroll events update it when the user actually moves.
          if (appliedTop === null || Math.abs(history.scrollTop - appliedTop) > 1) {
            followBottom = distanceToLatest() <= 24;
            position = readPosition() || position;
            appliedTop = history.scrollTop;
          }
        }
        persist();
      };
      const apply = () => {
        frame = 0;
        if (!current()) return;
        if (!initialized) {
          const pending = openingRequest();
          const request = pending?.key === key ? pending : null;
          const row = findRow(saved?.anchor?.id);
          // A validated cache containing the saved anchor (or the latest page)
          // may render immediately. Otherwise wait for the requested window.
          const cachedPositionReady = request?.hasCache &&
            (!saved || saved.bottom === true || row);
          if (request && !request.windowReady && !cachedPositionReady) return;
          if (options.chatState.messagesLoading && !request) return;
          const unreadRow = unreadAnchor?.key === key &&
            findRow("message:" + unreadAnchor.id);
          if (forced || saved?.bottom === true || (!saved && !unreadRow)) {
            followBottom = true;
            history.scrollTop = history.scrollHeight;
          } else if (saved) {
            history.scrollTop = row ? history.scrollTop + row.getBoundingClientRect().top -
              history.getBoundingClientRect().top - (saved.anchor.offset || 0) : saved.top;
            // Older persisted positions did not have an explicit bottom flag.
            followBottom = saved.bottom == null && distanceToLatest() <= 2;
          } else if (unreadRow) {
            history.scrollTop += unreadRow.getBoundingClientRect().top -
              history.getBoundingClientRect().top;
          }
          if (unreadAnchor?.key === key) unreadAnchor = null;
          initialized = true;
          forced = false;
          appliedTop = history.scrollTop;
          position = !followBottom && row && saved?.anchor
            ? { ...saved, top: history.scrollTop, bottom: false }
            : readPosition() || position;
          setPositionedKey(name);
        } else if (forced || followBottom) {
          history.scrollTop = history.scrollHeight;
          followBottom = true;
          forced = false;
          appliedTop = history.scrollTop;
          position = readPosition() || position;
        } else {
          const row = findRow(position?.anchor?.id);
          if (row) {
            const delta = row.getBoundingClientRect().top -
              history.getBoundingClientRect().top - position.anchor.offset;
            if (Math.abs(delta) > 0.5) history.scrollTop += delta;
          } else {
            position = readPosition() || position;
          }
          appliedTop = history.scrollTop;
        }
        setShowLatest(distanceToLatest() > 24);
      };
      const scheduleLatest = (force = false) => {
        if (force) {
          forced = true;
          followBottom = true;
        }
        if (!frame) frame = window.requestAnimationFrame(apply);
      };
      const handleScroll = () => {
        if (!initialized || !current()) return;
        if (!forced && (appliedTop === null || Math.abs(history.scrollTop - appliedTop) > 1)) {
          followBottom = distanceToLatest() <= 24;
          position = readPosition() || position;
          appliedTop = history.scrollTop;
        }
        setShowLatest(distanceToLatest() > 24);
        if (!captureTimer) captureTimer = window.setTimeout(() => {
          captureTimer = 0;
          persist();
        }, 100);
      };
      // Every message can resize after an image loads or content-visibility
      // reveals it. Observe all rows, not just the last one.
      const resizeObserver = typeof ResizeObserver === "function"
        ? new ResizeObserver(() => scheduleLatest())
        : null;
      const observed = new Set();
      const observeRows = () => {
        if (!resizeObserver) return;
        const rows = new Set(history.children);
        for (const row of observed) {
          if (!rows.has(row)) {
            resizeObserver.unobserve(row);
            observed.delete(row);
          }
        }
        for (const row of rows) {
          if (!observed.has(row)) {
            resizeObserver.observe(row);
            observed.add(row);
          }
        }
      };
      const mutationObserver = typeof MutationObserver === "function"
        ? new MutationObserver(() => {
            observeRows();
            scheduleLatest();
          })
        : null;
      history.addEventListener("scroll", handleScroll, { passive: true });
      resizeObserver?.observe(history);
      mutationObserver?.observe(history, { childList: true });
      observeRows();
      capturePosition = capture;
      schedulePosition = scheduleLatest;
      requestLatestScroll = () => scheduleLatest(true);
      const onVisibilityChange = () => {
        if (document.hidden) capture();
      };
      document.addEventListener("visibilitychange", onVisibilityChange);
      window.addEventListener("pagehide", capture);
      scheduleLatest();
      return () => {
        if (frame) window.cancelAnimationFrame(frame);
        window.clearTimeout(captureTimer);
        capture();
        setPositionedKey("");
        setShowLatest(false);
        document.removeEventListener("visibilitychange", onVisibilityChange);
        window.removeEventListener("pagehide", capture);
        history.removeEventListener("scroll", handleScroll);
        resizeObserver?.disconnect();
        mutationObserver?.disconnect();
        capturePosition = () => {};
        schedulePosition = () => {};
        requestLatestScroll = () => {};
      };
    },
  );
  return {
    savedPosition,
    capture: () => capturePosition(),
    schedule: () => schedulePosition(),
    scrollToLatest: () => requestLatestScroll(),
    setUnreadAnchor: (anchor) => { unreadAnchor = anchor; },
    get showLatest() { return showLatest(); },
    get positionReady() {
      return positionedKey() === positionName(activeChatKey(), options.chatState.messageFilter);
    },
  };
}
