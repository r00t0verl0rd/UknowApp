import { useCallback, useEffect, useMemo, useState } from "react";
import { createApiClient } from "../../../services/api.js";
import { getAdminBootstrap, getCurrentProfile, getInboxData } from "../../services/panelApi.js";

export function usePanelDataState({
  auth, setAuth, setProfile, setError, setChats,
  setPersonalChats, setUsers, setOverview,
  setSelectedChat, setMessages,
}) {
  const request = useMemo(() => createApiClient(), []);
  const [panelReady, setPanelReady] = useState(false);

  const refresh = useCallback(async () => {
    if (!auth) return;
    setError("");
    try {
      const who = await getCurrentProfile(request);
      setProfile(who);

      const adminRequest = who.role === "admin" ? getAdminBootstrap(request) : Promise.resolve(null);
      const [[conversations, personal], adminData] = await Promise.all([
        getInboxData(request), adminRequest,
      ]);
      setChats(conversations);
      setPersonalChats(personal);
      if (who.role === "admin") {
        const [people, summary] = adminData;
        setUsers(people);
        setOverview(summary);
      } else {
        setUsers([]);
        setOverview(null);
        if (who.role !== "teacher") {
          setSelectedChat(null);
          setMessages([]);
        }
      }
      setPanelReady(true);
    } catch (error) {
      setPanelReady(true);
      setError(error.message);
      const message = String(error.message).toLowerCase();
      if (["учитель", "ученик", "логин", "сессия", "войдите", "учётная запись"].some(term => message.includes(term)) || message.includes("401")) {
        localStorage.removeItem("uknowapp-auth");
        sessionStorage.removeItem("uknowapp-auth");
        setAuth("");
        setProfile(null);
      }
    }
  }, [auth, request]);

  useEffect(() => {
    if (!auth) setPanelReady(false);
  }, [auth]);

  useEffect(() => { void refresh(); }, [refresh]);


  return { request, refresh, panelReady };
}
