import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createApiClient } from "../../../services/api.js";
import { getAdminBootstrap, getCurrentProfile, getInboxData } from "../../services/panelApi.js";

export function usePanelDataState({
  auth, setAuth, setProfile, setError, setChats,
  setPersonalChats, setUsers, setOverview,
  setSelectedChat, setMessages,
}) {
  const request = useMemo(() => createApiClient(), []);
  const [panelReady, setPanelReady] = useState(false);
  const refreshRevision = useRef(0);

  const refresh = useCallback(async () => {
    if (!auth) return;
    const revision = ++refreshRevision.current;
    setError("");
    let who;
    try {
      who = await getCurrentProfile(request);
      if (revision !== refreshRevision.current) return;
      setProfile(who);
      // The application shell only depends on the authenticated profile.
      // Inbox and role-specific data continue loading without blocking it.
      setPanelReady(true);
    } catch (error) {
      if (revision !== refreshRevision.current) return;
      setPanelReady(true);
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

    const inboxTask = getInboxData(request).then(([conversations, personal]) => {
      if (revision !== refreshRevision.current) return;
      setChats(conversations);
      setPersonalChats(personal);
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
  }, [auth, request]);

  useEffect(() => {
    refreshRevision.current += 1;
    if (!auth) setPanelReady(false);
  }, [auth]);

  useEffect(() => { void refresh(); }, [refresh]);


  return { request, refresh, panelReady };
}
