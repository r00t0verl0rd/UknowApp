import { useEffect, useRef } from "react";
import { createPanelEventSource, getInboxData } from "../../../shared/services/panelApi.js";
import { getChatMessage, getChatMessages, getChatSummary } from "../services/conversationsApi.js";

const maxMessageId = rows => rows.reduce((max, row) => Math.max(max, Number(row.id) || 0), 0);

const isSameChat = (chat, id, type) => (
  Number(chat?.id) === Number(id)
  && (chat?.type === "personal") === (type === "personal")
);

function mergeMessages(previous, incoming) {
  if (!incoming.length) return previous;
  const clientIds = new Set(
    incoming.map(item => item.metadata?.client_message_id).filter(Boolean),
  );
  const incomingById = new Map(incoming.map(item => [item.id, item]));
  const merged = previous
    .filter(item => !clientIds.has(item.metadata?.client_message_id))
    .map(item => incomingById.has(item.id) ? incomingById.get(item.id) : item);
  const known = new Set(merged.map(item => item.id));
  return [
    ...merged,
    ...incoming.filter(item => !known.has(item.id)),
  ];
}

export function useConversationSync({
  auth, page, role, selectedChat, messages, request,
  setChats, setPersonalChats, setSelectedChat, setMessages,
}) {
  const current = useRef(null);
  const lastMessageId = useRef(0);
  const pending = useRef(new Map());
  const processing = useRef(false);

  current.current = {
    selectedChat, messages, role,
    setChats, setPersonalChats, setSelectedChat, setMessages,
  };

  useEffect(() => {
    lastMessageId.current = 0;
  }, [selectedChat?.id, selectedChat?.type]);

  useEffect(() => {
    if (messages.length) {
      lastMessageId.current = Math.max(
        lastMessageId.current,
        maxMessageId(messages),
      );
    }
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
        maxMessageId(current.current.messages),
      );
      const rows = await getChatMessages(request, chat, afterId);
      if (!active || !isSameChat(current.current.selectedChat, chat.id, chat.type)) return;
      if (fullHistory) {
        lastMessageId.current = maxMessageId(rows);
        current.current.setMessages(rows);
      } else if (rows.length) {
        lastMessageId.current = Math.max(afterId, maxMessageId(rows));
        current.current.setMessages(previous => mergeMessages(previous, rows));
      }
    };

    const refreshOneMessage = async (chat, messageId) => {
      try {
        const row = await getChatMessage(request, chat, messageId);
        if (!active || !isSameChat(current.current.selectedChat, chat.id, chat.type)) return;
        current.current.setMessages(previous => mergeMessages(previous, [row]));
      } catch {
        // A concurrent deletion or a revoked conversation is reconciled by its next event.
      }
    };

    const refreshSummary = async (type, id) => {
      const chat = { id, type: type === "personal" ? "personal" : "conversation" };
      try {
        const summary = await getChatSummary(request, chat);
        if (!active) return;
        applySummary(type, id, summary);
      } catch (error) {
        if (!/404|не найден/i.test(String(error.message))) throw error;
        if (type === "personal") {
          current.current.setPersonalChats(items => items.filter(item => Number(item.id) !== Number(id)));
        } else {
          current.current.setChats(items => items.filter(item => Number(item.id) !== Number(id)));
        }
      }
    };

    const applySummary = (type, id, summary) => {
      if (!summary || !active) return;
      if (type === "personal") {
        current.current.setPersonalChats(items => items.some(item => Number(item.id) === Number(id))
          ? items.map(item => Number(item.id) === Number(id) ? { ...item, ...summary } : item)
          : [summary, ...items]);
      } else {
        current.current.setChats(items => items.some(item => Number(item.id) === Number(id))
          ? items.map(item => Number(item.id) === Number(id) ? { ...item, ...summary } : item)
          : [summary, ...items]);
      }
      current.current.setSelectedChat(previous => (
        isSameChat(previous, id, type) ? { ...previous, ...summary } : previous
      ));
    };

    const recover = async () => {
      await refreshInbox();
      await refreshSelected(true);
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
              conversation_id: id,
              conversation_type: type,
              deleted_message_ids: deletedIds,
              updated_message_ids: updatedIds,
              refresh_messages: refreshMessages,
              needs_summary: needsSummary,
            } = event;
            const chat = current.current.selectedChat;
            if (isSameChat(chat, id, type)) {
              if (deletedIds.size) {
                current.current.setMessages(rows => rows.filter(
                  row => !deletedIds.has(Number(row.id)),
                ));
              }
              const jobs = [];
              if (refreshMessages) jobs.push(refreshSelected());
              for (const messageId of updatedIds) {
                jobs.push(refreshOneMessage(chat, messageId));
              }
              await Promise.all(jobs);
            }
            if (needsSummary) await refreshSummary(type, Number(id));
          }));
        }
      } catch {
        // A reconnect or queue-overflow resync restores the authoritative snapshot.
      } finally {
        processing.current = false;
        if (pending.current.size && active) void flush();
      }
    };

    const source = createPanelEventSource();
    let fallbackTimer = null;
    let hasOpened = false;
    const stopFallback = () => {
      if (fallbackTimer !== null) {
        window.clearInterval(fallbackTimer);
        fallbackTimer = null;
      }
    };
    const startFallback = () => {
      if (fallbackTimer !== null) return;
      // SSE is authoritative; use a low-frequency fallback only while disconnected.
      fallbackTimer = window.setInterval(() => {
        if (document.visibilityState !== "visible") return;
        void refreshInbox()
          .then(() => refreshSelected())
          .catch(() => {});
      }, 3000);
    };

    if (!source) {
      startFallback();
    } else {
      source.onopen = () => {
        stopFallback();
        if (hasOpened) {
          void recover().catch(() => {});
        } else {
          hasOpened = true;
          void refreshInbox()
            .then(() => refreshSelected())
            .catch(() => {});
        }
      };
      source.onerror = () => startFallback();
      source.addEventListener("update", event => {
        let payload;
        try {
          payload = JSON.parse(event.data || "{}");
        } catch {
          payload = { resync: true };
        }
        if (payload.resync) {
          void recover().catch(() => {});
          return;
        }
        if (!payload.conversation_id) return;

        const id = Number(payload.conversation_id);
        const type = payload.conversation_type || "conversation";
        if (payload.summary) applySummary(type, id, payload.summary);

        const selected = current.current.selectedChat;
        const viewerRole = current.current.role;
        const expectedReader = selected?.type === "personal"
          ? (viewerRole === "admin" ? selected.participant?.role : "admin")
          : viewerRole === "teacher" ? "student"
            : viewerRole === "student" ? "teacher" : null;

        if (
          payload.action === "read"
          && isSameChat(selected, id, type)
          && Array.isArray(payload.message_ids)
          && payload.message_ids.length
        ) {
          if (viewerRole === "admin" && type !== "personal") {
            // Admin receipts require both participants to have read the message.
            // Re-read only the affected row so the shared two-reader state stays authoritative.
            for (const messageId of payload.message_ids) {
              void refreshOneMessage(selected, Number(messageId));
            }
          } else if (expectedReader === payload.actor_role) {
            const readIds = new Set(payload.message_ids.map(Number));
            const readAt = payload.read_at || new Date().toISOString();
            current.current.setMessages(rows => rows.map(row => (
              readIds.has(Number(row.id)) && row.sender_role === viewerRole && !row.panel_read_at
                ? { ...row, panel_read_at: readAt }
                : row
            )));
          }
        }

        const key = type + ":" + id;
        const state = pending.current.get(key) || {
          conversation_id: id,
          conversation_type: type,
          deleted_message_ids: new Set(),
          updated_message_ids: new Set(),
          refresh_messages: false,
          needs_summary: false,
        };
        if (payload.action === "delete" && payload.message_id) {
          state.deleted_message_ids.add(Number(payload.message_id));
        } else if (payload.action === "delivery" && payload.message_id) {
          state.updated_message_ids.add(Number(payload.message_id));
        } else if (payload.action !== "read") {
          state.refresh_messages = true;
        }
        if (!payload.summary) state.needs_summary = true;
        pending.current.set(key, state);
        void flush();
      });
    }

    const onVisibilityChange = () => {
      if (document.visibilityState === "visible") {
        void refreshInbox().then(() => refreshSelected()).catch(() => {});
      }
    };
    document.addEventListener("visibilitychange", onVisibilityChange);
    return () => {
      active = false;
      pending.current.clear();
      source?.close();
      stopFallback();
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
  }, [auth, page, request]);
}
