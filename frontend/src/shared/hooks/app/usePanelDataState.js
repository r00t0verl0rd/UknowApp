import { useCallback, useEffect, useMemo, useState } from "react";
import { createApiClient } from "../../../services/api.js";
import { createPanelEventSource, getAdminBootstrap, getCurrentProfile, getInboxData } from "../../services/panelApi.js";
import { getChatMessages } from "../../../features/conversations/services/conversationsApi.js";

export function usePanelDataState({
  auth, page, selectedChat, setAuth, setProfile, setError, setChats,
  setPersonalChats, setUsers, setOverview, setPage,
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
      setPanelReady(true);

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
          setPage("chats");
          setSelectedChat(null);
          setMessages([]);
        }
      }
      setPanelReady(true);
    } catch (error) {
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

  useEffect(() => {
    if (!auth || page !== "chats") return undefined;
    let active = true;
    let inFlight = false;
    let refreshPending = false;
    let refreshMessagesPending = false;

    const syncChats = async (event, forceMessages = false) => {
      if (!active) return;
      let shouldRefreshMessages = forceMessages;
      if (event) {
        let eventConversationId = null;
        if (event.data) {
          try {
            eventConversationId = Number(JSON.parse(event.data).conversation_id) || null;
          } catch {
            // Malformed events trigger a general inbox refresh.
          }
        }
        shouldRefreshMessages = !eventConversationId
          || eventConversationId === Number(selectedChat?.id);
      }
      if (inFlight) {
        refreshPending = true;
        refreshMessagesPending ||= Boolean(selectedChat?.id && shouldRefreshMessages);
        return;
      }
      inFlight = true;
      try {
        if (selectedChat?.id && shouldRefreshMessages) {
          const rows = await getChatMessages(request, selectedChat);
          if (!active) return;
          setMessages(rows);
        }
        const [conversations, personal] = await getInboxData(request);
        if (!active) return;
        setChats(conversations);
        setPersonalChats(personal);
      } catch {
        // Preserve the current view during transient network failures.
      } finally {
        inFlight = false;
        if (refreshPending && active) {
          const reloadMessages = refreshMessagesPending;
          refreshPending = false;
          refreshMessagesPending = false;
          void syncChats(null, reloadMessages);
        }
      }
    };

    const eventSource = createPanelEventSource();
    eventSource.addEventListener("update", syncChats);
    const onVisibilityChange = () => {
      if (document.visibilityState === "visible") void syncChats(null, true);
    };
    document.addEventListener("visibilitychange", onVisibilityChange);

    return () => {
      active = false;
      eventSource.close();
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
  }, [auth, page, selectedChat?.id, selectedChat?.type, request]);

  return { request, refresh, panelReady };
}
