import { useCallback, useEffect, useMemo, useRef } from "react";
import { createApiClient } from "../../../services/api.js";
import { getAdminBootstrap, getCurrentProfile, getInboxData } from "../../services/panelApi.js";
import { mergeInboxSnapshot } from "../../services/inboxState.js";

export function usePanelDataState({
  auth, setAuth, setProfile, setError, setChats,
  setPersonalChats, setUsers, setOverview,
  setSelectedChat, setMessages,
}) {
  const request = useMemo(() => createApiClient(), []);
  const refreshRevision = useRef(0);
  const refreshTask = useRef(null);
  const inboxRevision = useRef(0);

  const refresh = useCallback(() => {
    if (!auth) return Promise.resolve();
    if (refreshTask.current) return refreshTask.current;
    const task = (async () => {
    const revision = ++refreshRevision.current;
    setError("");
    let who;
    try {
      who = await getCurrentProfile(request);
      if (revision !== refreshRevision.current) return;
      setProfile(who);
    } catch (error) {
      if (revision !== refreshRevision.current) return;
      setError(error.message);
      const message = String(error.message).toLowerCase();
      if (["учитель", "ученик", "логин", "сессия", "войдите", "учётная запись"].some(term => message.includes(term)) || message.includes("401")) {
        localStorage.removeItem("uknowapp-auth");
        sessionStorage.removeItem("uknowapp-auth");
        setAuth("");
        setProfile(null);
      }
      return;
    }

    const inboxRevisionAtStart = inboxRevision.current;
    const inboxTask = getInboxData(request).then(([conversations, personal]) => {
      if (revision !== refreshRevision.current) return;
      if (inboxRevisionAtStart === inboxRevision.current) {
        setChats(conversations);
        setPersonalChats(personal);
        return;
      }
      // SSE changed one or more rows while the initial snapshot was loading.
      // Merge that live state over the snapshot instead of rolling it back.
      setChats(current => mergeInboxSnapshot(conversations, current));
      setPersonalChats(current => mergeInboxSnapshot(personal, current));
    });
    const adminTask = who.role === "admin"
      ? getAdminBootstrap(request).then(([people, summary]) => {
        if (revision !== refreshRevision.current) return;
        setUsers(people);
        setOverview(summary);
      })
      : Promise.resolve().then(() => {
        if (revision !== refreshRevision.current) return;
        setUsers([]);
        setOverview(null);
        if (who.role !== "teacher") {
          setSelectedChat(null);
          setMessages([]);
        }
      });

    const results = await Promise.allSettled([inboxTask, adminTask]);
    if (revision !== refreshRevision.current) return;
    const failed = results.find(result => result.status === "rejected");
    if (failed) setError(failed.reason?.message || "Не удалось загрузить часть данных приложения");
    })();
    refreshTask.current = task;
    task.then(
      () => { if (refreshTask.current === task) refreshTask.current = null; },
      () => { if (refreshTask.current === task) refreshTask.current = null; },
    );
    return task;
  }, [auth, request]);

  useEffect(() => {
    if (!auth) {
      refreshRevision.current += 1;
      refreshTask.current = null;
    }
  }, [auth]);

  useEffect(() => { void refresh(); }, [refresh]);

  return { request, refresh, inboxRevision };
}
