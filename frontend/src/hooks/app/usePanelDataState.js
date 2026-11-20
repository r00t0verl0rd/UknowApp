import { useCallback, useEffect, useMemo, useState } from "react";
import { createApiClient } from "../../services/api.js";
import { createPanelEventSource, getAdminBootstrap, getCurrentProfile, getInboxData, getTeacherGraph } from "../../modules/panel/services/panelApi.js";
import { getChatMessages } from "../../modules/conversations/services/conversationsApi.js";

export function usePanelDataState({
  auth, page, selectedChat, setAuth, setProfile, setError, setChats,
  setPersonalChats, setUsers, setOverview, setTeacherGraph, setPage,
  setSelectedChat, setMessages,
}) {
  const request = useMemo(() => createApiClient(), []);\n  const [panelReady, setPanelReady] = useState(false);

  const refresh = useCallback(async () => {
    if (!auth) return;
    setError("");
    try {
      const who = await getCurrentProfile(request);
      setProfile(who);

      const roleRequest = who.role === "admin"
        ? getAdminBootstrap(request)
        : who.role === "teacher" ? getTeacherGraph(request) : Promise.resolve(null);
      const [[conversations, personal], roleData] = await Promise.all([
        getInboxData(request), roleRequest,
      ]);
      setChats(conversations);
      setPersonalChats(personal);
      if (who.role === "admin") {
        const [people, summary] = roleData;
        setUsers(people);
        setOverview(summary);
      } else if (who.role === "teacher") {
        setTeacherGraph(roleData);
        setUsers([]);
        setOverview(null);
      } else {
        setTeacherGraph(null);
        setUsers([]);
        setOverview(null);
        setPage("chats");
        setSelectedChat(null);
        setMessages([]);
      }
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

  useEffect(() => {\n    if (!auth) setPanelReady(false);\n  }, [auth]);\n\n  useEffect(() => { void refresh(); }, [refresh]);

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
