import { createSignal, createEffect } from "solid-js";
import { request } from "../../services/api.js";
import { getAdminBootstrap, getCurrentProfile, getInboxData } from "../../services/panelApi.js";
import { mergeInboxSnapshot } from "../../services/inboxState.js";
export function createPanelDataState(options) {
  let refreshRevision = 0;
  let refreshTask = null;
  const inboxRowRevision = new Map();
  const [inboxLoading, setInboxLoading] = createSignal(false);
  const [adminDataLoading, setAdminDataLoading] = createSignal(false);
  const refresh = () => {
    if (!options.auth) return Promise.resolve();
    if (refreshTask) return refreshTask;
    const task = (async () => {
      const revision = ++refreshRevision;
      const revisionsAtStart = new Map(inboxRowRevision);
      const profileTask = getCurrentProfile(request);
      // Запускаем запросы вместе; показываем сообщения только после проверки сессии.
      const inboxResult = getInboxData(request).catch(() => null);
      let who;
      try {
        who = await profileTask;
        if (revision !== refreshRevision) return;
        options.setProfile(who);
        setInboxLoading(true);
        setAdminDataLoading(who.role === "admin");
      } catch (error) {
        if (revision !== refreshRevision) return;
        options.setError(error.message);
        const message = String(error.message).toLowerCase();
        if (
          ["учитель", "ученик", "логин", "сессия", "войдите", "учётная запись"].some((term) =>
            message.includes(term),
          ) ||
          message.includes("401")
        ) {
          localStorage.removeItem("uknowapp-auth");
          sessionStorage.removeItem("uknowapp-auth");
          options.setAuth("");
          options.setProfile(null);
        }
        return;
      }
      const inboxTask = inboxResult
        .then((data) => {
          if (!data) return;
          const [conversations, personal] = data;
          if (revision !== refreshRevision) return;
          const changedRows = new Set(
            [...inboxRowRevision]
              .filter(([key, value]) => value > (revisionsAtStart.get(key) || 0))
              .map(([key]) => key),
          );
          const changedConversations = new Set(
            [...changedRows]
              .filter((key) => key.startsWith("conversation:"))
              .map((key) => Number(key.slice("conversation:".length))),
          );
          const changedPersonal = new Set(
            [...changedRows]
              .filter((key) => key.startsWith("personal:"))
              .map((key) => Number(key.slice("personal:".length))),
          );
          options.setChats((current) => mergeInboxSnapshot(conversations, current, changedConversations));
          options.setPersonalChats((current) => mergeInboxSnapshot(personal, current, changedPersonal));
        })
        .finally(() => {
          if (revision === refreshRevision) setInboxLoading(false);
        });
      const adminTask =
        who.role === "admin"
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
      if (who.role !== "admin") {
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
    get inboxLoading() {
      return inboxLoading();
    },
    get adminDataLoading() {
      return adminDataLoading();
    },
  };
}
