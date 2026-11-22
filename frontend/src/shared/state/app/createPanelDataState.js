import { createSignal, createEffect } from "solid-js";
import { request } from "../../services/api.js";
import { getAdminBootstrap, getCurrentProfile } from "../../services/panelApi.js";
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
      // Разные источники переписок рисуем независимо: медленный ответ
      // личных диалогов не задерживает появление обычных, и наоборот.
      const conversationsResult = request("/api/panel/conversations").catch(() => null);
      const personalResult = request("/api/panel/personal-conversations").catch(() => null);
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
