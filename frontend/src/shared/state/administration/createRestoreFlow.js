import { createEffect, createSignal } from "solid-js";
import { getRestoreStatus } from "../../../features/administration/services/adminDataApi.js";

// A restore replaces the backend database and often invalidates the current session.
// Remember only the restore ID and UI phase in this tab, never credentials or file bytes.
export const RESTORE_FLOW_KEY = "uknowapp-restore-flow-v1";
const MAX_FLOW_AGE = 24 * 60 * 60 * 1000;
const SLOW_RESTORE_AFTER = 3 * 60 * 1000;
const storedPhases = new Set(["waiting", "reauth", "login", "delayed", "completed", "failed"]);

export function readRestoreFlow(storage, now = Date.now()) {
  try {
    const raw = storage.getItem(RESTORE_FLOW_KEY);
    if (!raw) return null;
    const saved = JSON.parse(raw);
    if (typeof saved.id !== "string" || !saved.id || !storedPhases.has(saved.phase) ||
        !Number.isFinite(saved.startedAt) || saved.startedAt > now ||
        now - saved.startedAt > MAX_FLOW_AGE) {
      storage.removeItem(RESTORE_FLOW_KEY);
      return null;
    }
    return saved;
  } catch {
    return null;
  }
}

export function createRestoreFlow(options) {
  const [flow, setFlow] = createSignal(readRestoreFlow(sessionStorage));
  const persist = value => {
    if (value?.id) {
      sessionStorage.setItem(RESTORE_FLOW_KEY, JSON.stringify({
        id: value.id,
        phase: value.phase,
        startedAt: value.startedAt,
        automaticRestart: value.automaticRestart,
      }));
    } else {
      sessionStorage.removeItem(RESTORE_FLOW_KEY);
    }
    setFlow(value);
  };

  const startUpload = () => {
    persist({ phase: "uploading" });
  };
  const uploadFailed = () => {
    if (flow()?.phase === "uploading") persist(null);
  };
  const beginRestore = result => {
    persist({
      id: result.restore_id,
      phase: "waiting",
      startedAt: Date.now(),
      automaticRestart: result.automatic_restart !== false,
    });
  };
  const isInProgress = () => ["uploading", "waiting", "delayed", "reauth"].includes(flow()?.phase);
  const suppressUnexpectedLogout = () => Boolean(flow()?.id) && flow()?.phase !== "login";

  // Monitor at app level, outside the lazily loaded admin page, so navigation
  // and an expired server session cannot make restore progress disappear.
  createEffect(
    () => [flow()?.id, flow()?.phase, options.auth],
    () => {
      const current = flow();
      if (current?.phase === "login" && options.auth) {
        persist({ ...current, phase: "waiting", startedAt: Date.now() });
        return undefined;
      }
      if (current?.phase !== "waiting" || !current.id || !options.auth) return undefined;
      const controller = new AbortController();
      let timer;
      let interval = 1000;
      const poll = async () => {
        try {
          const result = await getRestoreStatus(controller.signal);
          if (controller.signal.aborted || flow()?.id !== current.id) return;
          if (result?.status === "login") {
            persist({ ...flow(), phase: "reauth" });
            return;
          }
          if (result?.id === current.id && ["completed", "failed"].includes(result.status)) {
            persist({ ...flow(), phase: result.status, finishedAt: result.finished_at });
            return;
          }
        } catch {
          // A transient 502/503 during backend restart is expected; keep polling.
        }
        if (controller.signal.aborted || flow()?.id !== current.id) return;
        if (Date.now() - current.startedAt >= SLOW_RESTORE_AFTER) {
          persist({ ...flow(), phase: "delayed" });
          return;
        }
        interval = Math.min(Math.round(interval * 1.5), 5000);
        timer = window.setTimeout(poll, interval);
      };
      timer = window.setTimeout(poll, 1000);
      return () => {
        controller.abort();
        window.clearTimeout(timer);
      };
    },
  );
  const confirmRelogin = () => {
    const current = flow();
    if (current?.phase !== "reauth") return;
    persist({ ...current, phase: "login" });
    // This session is already invalid server-side. Only end the browser session
    // after the user explicitly agrees, and keep the restore marker for re-login.
    localStorage.removeItem("uknowapp-auth");
    sessionStorage.removeItem("uknowapp-auth");
    window.location.assign("/");
  };
  const retry = () => {
    if (flow()?.phase === "delayed") persist({ ...flow(), phase: "waiting", startedAt: Date.now() });
  };
  const dismiss = () => {
    if (["completed", "failed"].includes(flow()?.phase)) persist(null);
  };
  return {
    get current() { return flow(); },
    get phase() { return flow()?.phase || ""; },
    get isInProgress() { return isInProgress(); },
    get isBlocking() { return Boolean(flow()) && !["completed", "failed", "login"].includes(flow()?.phase); },
    get needsLogin() { return flow()?.phase === "login"; },
    suppressUnexpectedLogout,
    startUpload,
    uploadFailed,
    beginRestore,
    confirmRelogin,
    retry,
    dismiss,
  };
}
