import { useEffect, useRef } from "react";
import { createPanelEventSource, getInboxData } from "../../../shared/services/panelApi.js";
import { syncChatState } from "../services/conversationsApi.js";

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
  const incomingById = new Map(incoming.map(item => [Number(item.id), item]));
  const merged = previous
    .filter(item => !clientIds.has(item.metadata?.client_message_id))
    .map(item => {
      const update = incomingById.get(Number(item.id));
      return update
        ? { ...item, ...update, metadata: { ...(item.metadata || {}), ...(update.metadata || {}) } }
        : item;
    });
  const known = new Set(merged.map(item => Number(item.id)));
  return [
    ...merged,
    ...incoming.filter(item => !known.has(Number(item.id))),
  ];
}

export function useConversationSync({
  auth, page, role, selectedChat, messages, request,
  setChats, setPersonalChats, setSelectedChat, setMessages,
}) {
  const current = useRef(null);
  const lastMessageCursor = useRef({ chatKey: "", id: 0 });
  const lastEventId = useRef(0);
  const pending = useRef(new Map());
  const processing = useRef(false);
  const syncing = useRef(false);
  const syncQueued = useRef(false);

  current.current = {
    selectedChat, messages, role,
    setChats, setPersonalChats, setSelectedChat, setMessages,
  };

  useEffect(() => {
    if (!auth || page !== "chats") return undefined;
    let active = true;

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

    const refreshInbox = async () => {
      const [conversations, personal] = await getInboxData(request);
      if (!active) return;
      current.current.setChats(conversations);
      current.current.setPersonalChats(personal);
    };

    const syncSelected = async () => {
      if (document.visibilityState !== "visible") return;
      if (syncing.current) {
        syncQueued.current = true;
        return;
      }
      syncing.current = true;
      try {
        do {
          syncQueued.current = false;
          const chat = current.current.selectedChat;
          if (!chat || document.visibilityState !== "visible") break;
          const knownMessages = current.current.messages
            .filter(item => Number.isSafeInteger(Number(item.id)) && Number(item.id) > 0);
          const chatKey = chat.type + ":" + chat.id;
          if (lastMessageCursor.current.chatKey !== chatKey) {
            lastMessageCursor.current = { chatKey, id: maxMessageId(knownMessages) };
          }
          const afterId = Math.max(lastMessageCursor.current.id, maxMessageId(knownMessages));
          const result = await syncChatState(
            request,
            chat,
            afterId,
            knownMessages.map(item => Number(item.id)),
          );
          if (!active) break;
          if (!isSameChat(current.current.selectedChat, chat.id, chat.type)) {
            syncQueued.current = true;
            continue;
          }
          const updated = [...(result.updated_messages || []), ...(result.messages || [])];
          if (updated.length) {
            lastMessageCursor.current.id = Math.max(afterId, maxMessageId(updated));
            current.current.setMessages(previous => mergeMessages(previous, updated));
          }
          if (result.summary) applySummary(chat.type, chat.id, result.summary);
        } while (syncQueued.current && active);
      } finally {
        syncing.current = false;
        if (syncQueued.current && active && document.visibilityState === "visible") {
          void syncSelected().catch(() => {});
        }
      }
    };

    const recover = async () => {
      await refreshInbox();
      await syncSelected();
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
              refresh_messages: refreshMessages,
            } = event;
            const chat = current.current.selectedChat;
            if (isSameChat(chat, id, type)) {
              if (deletedIds.size) {
                current.current.setMessages(rows => rows.filter(
                  row => !deletedIds.has(Number(row.id)),
                ));
              }
              if (refreshMessages) await syncSelected();
            }
          }));
        }
      } catch {
        // Replayed events or the bounded resync endpoint restore only changed rows.
      } finally {
        processing.current = false;
        if (pending.current.size && active) void flush();
      }
    };

    const source = createPanelEventSource();
    if (source) {
      source.onopen = () => {
        // Replay Last-Event-ID covers committed events; targeted sync also repairs
        // the rare crash window between message commit and outbox persistence.
        void recover().catch(() => {});
      };
      source.onerror = () => {
        // EventSource owns reconnect/backoff; avoid periodic polling while offline.
      };
      source.addEventListener("update", event => {
        let payload;
        try {
          payload = JSON.parse(event.data || "{}");
        } catch {
          payload = { resync: true };
        }
        const eventId = Number(payload.event_id || event.lastEventId || 0);
        if (payload.resync) {
          if (Number.isSafeInteger(eventId) && eventId > lastEventId.current) {
            lastEventId.current = eventId;
          }
          void recover().catch(() => {});
          return;
        }
        if (Number.isSafeInteger(eventId) && eventId > 0) {
          if (eventId <= lastEventId.current) return;
          lastEventId.current = eventId;
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

        let requiresReceiptSync = false;
        if (
          payload.action === "read"
          && isSameChat(selected, id, type)
          && Array.isArray(payload.message_ids)
          && payload.message_ids.length
        ) {
          if (viewerRole === "admin" && type !== "personal") {
            // The admin tick turns blue only after both participants have read.
            // One batched sync refreshes all already loaded receipt states.
            requiresReceiptSync = true;
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
          refresh_messages: false,
        };
        if (requiresReceiptSync) state.refresh_messages = true;
        if (payload.action === "delete" && payload.message_id) {
          state.deleted_message_ids.add(Number(payload.message_id));
        } else if (payload.action === "read") {
          // Participant read events are applied directly above unless the admin
          // needs to reconcile the combined two-reader receipt.
        } else {
          state.refresh_messages = true;
        }
        pending.current.set(key, state);
        void flush();
      });
    } else {
      // All supported target browsers and the installed web app provide EventSource.
      // A one-shot state reconcile is safer than introducing a polling loop.
      void recover().catch(() => {});
    }

    const onVisibilityChange = () => {
      if (document.visibilityState === "visible") void recover().catch(() => {});
    };
    document.addEventListener("visibilitychange", onVisibilityChange);
    return () => {
      active = false;
      pending.current.clear();
      source?.close();
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
  }, [auth, page, request]);
}
