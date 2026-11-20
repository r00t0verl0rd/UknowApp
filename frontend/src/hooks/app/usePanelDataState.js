import { useCallback, useEffect, useMemo } from "react";
import { createApiClient } from "../../services/api.js";

const API = import.meta.env.VITE_API_BASE_URL || "";

export function usePanelDataState({
  auth, page, selectedChat, setAuth, setProfile, setError, setChats,
  setPersonalChats, setUsers, setOverview, setTeacherGraph, setPage,
  setSelectedChat, setMessages,
}) {
  const request = useMemo(() => createApiClient(), []);

  const refresh = useCallback(async () => {
    if (!auth) return;
    setError("");
    try {
      const who = await request("/api/panel/me");
      setProfile(who);

      const roleRequest = who.role === "admin"
        ? Promise.all([request("/api/admin/users"), request("/api/admin/overview")])
        : who.role === "teacher" ? request("/api/panel/graph") : Promise.resolve(null);
      const [conversations, roleData, personal] = await Promise.all([
        request("/api/panel/conversations"), roleRequest, request("/api/panel/personal-conversations"),
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
          const base = selectedChat.type === "personal"
            ? "/api/panel/personal-conversations/" : "/api/panel/conversations/";
          const rows = await request(base + selectedChat.id + "/messages");
          if (!active) return;
          setMessages(rows);
        }
        const [conversations, personal] = await Promise.all([
          request("/api/panel/conversations"), request("/api/panel/personal-conversations"),
        ]);
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

    const eventSource = new EventSource(API + "/api/panel/events", { withCredentials: true });
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
  }, [auth, page, selectedChat?.id, request]);

  return { request, refresh };
}
