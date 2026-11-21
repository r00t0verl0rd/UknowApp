import { useEffect, useRef } from "react";
import { createPanelEventSource, getInboxData } from "../../../shared/services/panelApi.js";
import { getChatMessages, getChatSummary } from "../services/conversationsApi.js";

const maxMessageId = rows => rows.reduce((max, row) => Math.max(max, Number(row.id) || 0), 0);

export function useConversationSync({
  auth, page, role, selectedChat, messages, request, setChats, setPersonalChats, setMessages,
}) {
  const current = useRef(null);
  const lastMessageId = useRef(0);
  const pending = useRef(new Map());
  const processing = useRef(false);

  current.current = { selectedChat, messages, role, setChats, setPersonalChats, setMessages };

  useEffect(() => {
    lastMessageId.current = 0;
  }, [selectedChat?.id, selectedChat?.type]);

  useEffect(() => {
    if (messages.length) lastMessageId.current = Math.max(lastMessageId.current, Number(messages[messages.length - 1].id) || 0);
  }, [messages]);

  useEffect(() => {
    if (!auth || page !== "chats") return undefined;
    let active = true;

    const refreshInbox = async () => {
      const [conversations, personal] = await getInboxData(request);
      if (!active) return;
      current.current.setChats(conversations);
      current.current.setPersonalChats(personal);
    };

    const refreshSelected = async (fullHistory = false) => {
      const chat = current.current.selectedChat;
      if (!chat) return;
      const afterId = fullHistory ? 0 : Math.max(
        lastMessageId.current,
        Number(current.current.messages[current.current.messages.length - 1]?.id) || 0,
      );
      const rows = await getChatMessages(request, chat, afterId);
      if (!active) return;
      if (fullHistory) {
        lastMessageId.current = maxMessageId(rows);
        current.current.setMessages(rows);
      } else if (rows.length) {
        lastMessageId.current = Math.max(afterId, maxMessageId(rows));
        current.current.setMessages(previous => {
          const known = new Set(previous.map(item => item.id));
          return [...previous, ...rows.filter(item => !known.has(item.id))];
        });
      }
    };

    const recover = async () => {
      await refreshInbox();
      await refreshSelected(true);
    };

    const updateSummary = async (type, id) => {
      const chat = { id, type: type === "personal" ? "personal" : "conversation" };
      let summary;
      try {
        summary = await getChatSummary(request, chat);
      } catch (error) {
        if (!/404|не найден/i.test(String(error.message))) throw error;
        if (type === "personal") current.current.setPersonalChats(items => items.filter(item => item.id !== id));
        else current.current.setChats(items => items.filter(item => item.id !== id));
        return;
      }
      if (!active) return;
      if (type === "personal") {
        current.current.setPersonalChats(items => items.some(item => item.id === id)
          ? items.map(item => item.id === id ? { ...item, ...summary } : item)
          : [...items, summary]);
      } else {
        current.current.setChats(items => items.map(item => item.id === id ? { ...item, ...summary } : item));
      }
    };

    const flush = async () => {
      if (processing.current || !active) return;
      processing.current = true;
      try {
        while (pending.current.size && active) {
          const events = [...pending.current.values()];
          pending.current.clear();
          await Promise.all(events.map(async event => {
            const {
              conversation_id: id, conversation_type: type,
              deleted_message_ids: deletedIds,
              refresh_messages: refreshMessages,
            } = event;
            if (!id) return;
            const chat = current.current.selectedChat;
            if (chat && Number(chat.id) === Number(id) && (chat.type === "personal") === (type === "personal")) {
              if (deletedIds.length) {
                const deleted = new Set(deletedIds.map(Number));
                current.current.setMessages(rows => rows.filter(row => !deleted.has(Number(row.id))));
              }
              if (refreshMessages) await refreshSelected();
            }
            await updateSummary(type, Number(id));
          }));
        }
      } catch {
        // Targeted reads are retried by reconnect recovery.
      } finally {
        processing.current = false;
        if (pending.current.size && active) void flush();
      }
    };

    const source = createPanelEventSource();
    source.onopen = () => { void recover().catch(() => {}); };
    source.addEventListener("update", event => {
      let payload;
      try { payload = JSON.parse(event.data || "{}"); } catch { payload = { resync: true }; }
      if (payload.resync) { void recover().catch(() => {}); return; }
      if (!payload.conversation_id) return;
      const type = payload.conversation_type || "conversation";
      const selected = current.current.selectedChat;
      const viewerRole = current.current.role;
      const expectedReader = viewerRole === "teacher" ? "student"
        : viewerRole === "student" ? "teacher" : null;
      if (
        payload.action === "read"
        && expectedReader === payload.actor_role
        && selected
        && Number(selected.id) === Number(payload.conversation_id)
        && (selected.type === "personal") === (type === "personal")
        && Array.isArray(payload.message_ids)
        && payload.message_ids.length
      ) {
        const readIds = new Set(payload.message_ids.map(Number));
        const readAt = new Date().toISOString();
        current.current.setMessages(rows => rows.map(row =>
          readIds.has(Number(row.id)) && row.sender_role === viewerRole && !row.panel_read_at
            ? { ...row, panel_read_at: readAt }
            : row
        ));
      }
      const key = type + ":" + payload.conversation_id;
      const eventState = pending.current.get(key) || {
        conversation_id: payload.conversation_id,
        conversation_type: type,
        deleted_message_ids: [],
        refresh_messages: false,
      };
      if (payload.action === "delete" && payload.message_id) {
        eventState.deleted_message_ids.push(payload.message_id);
      } else if (payload.action !== "read") {
        eventState.refresh_messages = true;
      }
      pending.current.set(key, eventState);
      void flush();
    });

    const onVisibilityChange = () => {
      if (document.visibilityState === "visible") void refreshSelected().catch(() => {});
    };
    document.addEventListener("visibilitychange", onVisibilityChange);
    return () => {
      active = false;
      pending.current.clear();
      source.close();
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
  }, [auth, page, request]);
}
