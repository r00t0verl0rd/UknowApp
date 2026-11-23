import { createSignal, createEffect } from "solid-js";
import { workspaceFor } from "../../../workspaces/workspaceRegistry.js";
import { request } from "../../services/api.js";
import { getAdminBootstrap, getCurrentProfile } from "../../services/panelApi.js";
import { mergeInboxSnapshot } from "../../services/inboxState.js";
export function createPanelDataState(options) {
  let refreshRevision = 0;
  let refreshTask = null;
  let retryTimer = null;
  const inboxRowRevision = new Map();
  const [inboxLoading, setInboxLoading] = createSignal(false);
  const [adminDataLoading, setAdminDataLoading] = createSignal(false);
  function closeWorkspace() {
    // The restored database may invalidate the old session. Keep the
    // confirmation dialog visible instead of silently reloading to login.
    if (options.restoreFlow?.suppressUnexpectedLogout()) return;
    localStorage.removeItem("uknowapp-auth");
    sessionStorage.removeItem("uknowapp-auth");
    options.setProfile(null);
    options.setAuth("");
    window.location.reload();
  }
  async function verifySession() {
    const profile = options.profile;
    if (!profile) return;
    try {
      const current = await getCurrentProfile(request);
      if (profile !== options.profile) return;
      if (current.id === profile.id && current.role === profile.role &&
          JSON.stringify(current.permissions) === JSON.stringify(profile.permissions)) return;
    } catch (error) {
      if (profile !== options.profile) return;
      if (error.status !== 401 && error.status !== 403) return;
    }
    closeWorkspace();
  }
  const refresh = () => {
    if (!options.auth) return Promise.resolve();
    if (refreshTask) return refreshTask;
    const task = (async () => {
      const revision = ++refreshRevision;
      const revisionsAtStart = new Map(inboxRowRevision);
      const profileTask = getCurrentProfile(request);
      let who;
      try {
        who = await profileTask;
        if (revision !== refreshRevision) return;
        if (!workspaceFor(who)) throw new Error("Не удалось подтвердить права доступа");
        if (options.profile && (options.profile.id !== who.id || options.profile.role !== who.role)) {
          if (options.restoreFlow?.suppressUnexpectedLogout()) return;
          options.setProfile(null);
          window.location.reload();
          return;
        }
        options.setProfile(who);
        setInboxLoading(true);
        setAdminDataLoading(who.permissions.includes("users.manage"));
      } catch (error) {
        if (revision !== refreshRevision) return;
        if (options.restoreFlow?.suppressUnexpectedLogout()) return;
        if (error.status !== 401 && error.status !== 403) {
          retryTimer = window.setTimeout(() => {
            retryTimer = null;
            void refresh();
          }, 2000);
          return;
        }
        options.setError(error.message);
        closeWorkspace();
        return;
      }
      const conversationsResult = request("/api/panel/conversations").catch(() => null);
      const personalResult = request("/api/panel/personal-conversations").catch(() => null);
      let inboxPending = 2;
      const applyInbox = (task, setter, kind) =>
        task
          .then((rows) => {
            if (!Array.isArray(rows) || revision !== refreshRevision) return;
            const changedIds = new Set(
              [...inboxRowRevision]
                .filter(([key, value]) =>
                  key.startsWith(kind + ":") && value > (revisionsAtStart.get(key) || 0),
                )
                .map(([key]) => Number(key.slice(kind.length + 1))),
            );
            setter((current) => mergeInboxSnapshot(rows, current, changedIds));
          })
          .finally(() => {
            inboxPending -= 1;
            if (revision === refreshRevision && inboxPending === 0) setInboxLoading(false);
          });
      const inboxTask = Promise.allSettled([
        applyInbox(conversationsResult, options.setChats, "conversation"),
        applyInbox(personalResult, options.setPersonalChats, "personal"),
      ]);
      const adminTask =
        who.permissions.includes("users.manage")
          ? getAdminBootstrap(request)
              .then(([people, summary]) => {
                if (revision !== refreshRevision) return;
                options.setUsers(people);
                options.setOverview(summary);
              })
              .finally(() => {
                if (revision === refreshRevision) setAdminDataLoading(false);
              })
          : Promise.resolve();
      if (!who.permissions.includes("users.manage")) {
        setAdminDataLoading(false);
        options.setUsers([]);
        options.setOverview(null);
        if (who.role !== "teacher") {
          options.setSelectedChat(null);
          options.setMessages([]);
        }
      }

      // Background layers settle independently; one optional failure must not
      // display a global warning over an otherwise usable workspace.
      await Promise.allSettled([inboxTask, adminTask]);
    })();
    refreshTask = task;
    task.then(
      () => {
        if (refreshTask === task) refreshTask = null;
      },
      () => {
        if (refreshTask === task) refreshTask = null;
      },
    );
    return task;
  };
  createEffect(
    () => [options.auth],
    () => {
      if (!options.auth) {
        refreshRevision += 1;
        refreshTask = null;
        if (retryTimer) window.clearTimeout(retryTimer);
        retryTimer = null;
        setInboxLoading(false);
        setAdminDataLoading(false);
      }
    },
  );
  createEffect(
    () => [options.auth],
    () => {
      void refresh();
    },
  );
  return {
    request,
    refresh,
    inboxRowRevision,
    verifySession,
    get inboxLoading() {
      return inboxLoading();
    },
    get adminDataLoading() {
      return adminDataLoading();
    },
  };
}
