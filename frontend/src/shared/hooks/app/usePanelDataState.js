import { useCallback, useEffect, useMemo, useRef, useState } from "react";
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
  const inboxRowRevision = useRef(new Map());
  const [inboxLoading, setInboxLoading] = useState(false);
  const [adminDataLoading, setAdminDataLoading] = useState(false);

  const refresh = useCallback(() => {
    if (!auth) return Promise.resolve();
    if (refreshTask.current) return refreshTask.current;
    const task = (async () => {
      const revision = ++refreshRevision.current;
      const revisionsAtStart = new Map(inboxRowRevision.current);
      const profileTask = getCurrentProfile(request);
      // Both requests start together. Keep inbox data private until the session is confirmed.
      const inboxResult = getInboxData(request).catch(() => null);
      let who;
      try {
        who = await profileTask;
        if (revision !== refreshRevision.current) return;
        setProfile(who);
        setInboxLoading(true);
        setAdminDataLoading(who.role === "admin");
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

      const inboxTask = inboxResult.then(data => {
        if (!data) return;
        const [conversations, personal] = data;
        if (revision !== refreshRevision.current) return;
        const changedRows = new Set(
          [...inboxRowRevision.current].filter(([key, value]) => (
            value > (revisionsAtStart.get(key) || 0)
          )).map(([key]) => key),
        );
        const changedConversations = new Set(
          [...changedRows].filter(key => key.startsWith("conversation:"))
            .map(key => Number(key.slice("conversation:".length))),
        );
        const changedPersonal = new Set(
          [...changedRows].filter(key => key.startsWith("personal:"))
            .map(key => Number(key.slice("personal:".length))),
        );
        setChats(current => mergeInboxSnapshot(conversations, current, changedConversations));
        setPersonalChats(current => mergeInboxSnapshot(personal, current, changedPersonal));
      }).finally(() => {
        if (revision === refreshRevision.current) setInboxLoading(false);
      });

      const adminTask = who.role === "admin"
        ? getAdminBootstrap(request).then(([people, summary]) => {
          if (revision !== refreshRevision.current) return;
          setUsers(people);
          setOverview(summary);
        }).finally(() => {
          if (revision === refreshRevision.current) setAdminDataLoading(false);
        })
        : Promise.resolve();

      if (who.role !== "admin") {
        setAdminDataLoading(false);
        setUsers([]);
        setOverview(null);
        if (who.role !== "teacher") {
          setSelectedChat(null);
          setMessages([]);
        }
      }

      // Background layers settle independently; one optional failure must not
      // display a global warning over an otherwise usable workspace.
      await Promise.allSettled([inboxTask, adminTask]);
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
      setInboxLoading(false);
      setAdminDataLoading(false);
    }
  }, [auth]);

  useEffect(() => { void refresh(); }, [refresh]);

  return { request, refresh, inboxRowRevision, inboxLoading, adminDataLoading };
}
