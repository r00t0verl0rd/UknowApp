import { useEffect, useRef } from "react";
import { createPanelEventSource, getInboxData } from "../../../shared/services/panelApi.js";
import { syncChatState } from "../services/conversationsApi.js";
import { mergeConversationMessages } from "../services/messageState.js";
import { mergeInboxSnapshot } from "../../../shared/services/inboxState.js";

const maxMessageId = rows => rows.reduce((max, row) => Math.max(max, Number(row.id) || 0), 0);

const isSameChat = (chat, id, type) => (
  Number(chat?.id) === Number(id)
  && (chat?.type === "personal") === (type === "personal")
);

const conversationKey = (id, type) => (type === "personal" ? "personal:" : "conversation:") + id;

export function useConversationSync({
  auth, role, selectedChat, messages, request, inboxRevision,
  setChats, setPersonalChats, setSelectedChat, setMessages,
}) {
  const current = useRef(null);
  const lastMessageCursor = useRef({ chatKey: "", id: 0 });
  const lastEventId = useRef(0);
  const pending = useRef(new Map());
  const processing = useRef(false);
  const syncing = useRef(false);
  const syncQueued = useRef(false);
  const eventRevision = useRef(new Map());
  const inboxRequestRevision = useRef(0);
  const inboxRowRevision = useRef(new Map());
  const recoveryPending = useRef(false);

  current.current = {
    selectedChat, messages, role,
    setChats, setPersonalChats, setSelectedChat, setMessages,
  };

  useEffect(() => {
    if (!auth) return undefined;
    let active = true;

    const applySummary = (type, id, summary) => {
      if (!summary || !active) return;
      inboxRevision.current += 1;
      const rowKey = conversationKey(id, type);
      inboxRowRevision.current.set(rowKey, (inboxRowRevision.current.get(rowKey) || 0) + 1);
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
      const requestRevision = ++inboxRequestRevision.current;
      const revisionsAtStart = new Map(inboxRowRevision.current);
      const [conversations, personal] = await getInboxData(request);
      if (!active || requestRevision !== inboxRequestRevision.current) return;

      const changedRows = new Set(
        [...inboxRowRevision.current].filter(([key, revision]) => (
          revision > (revisionsAtStart.get(key) || 0)
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
      current.current.setChats(items => mergeInboxSnapshot(conversations, items, changedConversations));
      current.current.setPersonalChats(items => mergeInboxSnapshot(personal, items, changedPersonal));
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
          const chatKey = conversationKey(chat.id, chat.type);
          if (lastMessageCursor.current.chatKey !== chatKey) {
            lastMessageCursor.current = { chatKey, id: maxMessageId(knownMessages) };
          }
          const afterId = Math.max(lastMessageCursor.current.id, maxMessageId(knownMessages));
          const revisionAtStart = eventRevision.current.get(chatKey) || 0;
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

          // A newer event for this dialog arrived while the request was in
          // flight. Do not let its older response overwrite the event state.
          // Run one fresh targeted sync with the latest cursor instead.
          if (revisionAtStart !== (eventRevision.current.get(chatKey) || 0)) {
            syncQueued.current = true;
            continue;
          }

          const updated = [...(result.updated_messages || []), ...(result.messages || [])];
          if (updated.length) {
            lastMessageCursor.current.id = Math.max(afterId, maxMessageId(updated));
            current.current.setMessages(previous => mergeConversationMessages(previous, updated));
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

    const recover = async ({ refreshInbox: refresh = false } = {}) => {
      try {
        if (refresh) await refreshInbox();
        await syncSelected();
        recoveryPending.current = false;
      } catch (error) {
        recoveryPending.current = true;
        throw error;
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
        // Event replay and targeted sync recover changed rows after transient errors.
      } finally {
        processing.current = false;
        if (pending.current.size && active) void flush();
      }
    };

    const source = createPanelEventSource();
    if (source) {
      source.onopen = () => {
        // The first connection does not reload inbox lists. On reconnect the
        // browser replays durable events using Last-Event-ID automatically.
        if (recoveryPending.current) {
          void recover({ refreshInbox: true }).catch(() => {});
        } else {
          void syncSelected().catch(() => {});
        }
      };
      source.onerror = () => {
        // EventSource owns reconnect/backoff; no periodic polling is required.
      };
      source.addEventListener("update", event => {
        let payload;
        try {
          payload = JSON.parse(event.data || "{}");
        } catch {
          payload = { resync: true };
        }
        const eventId = Number(payload.event_id || event.lastEventId || 0);
        if (Number.isSafeInteger(eventId) && eventId > 0) {
          if (eventId <= lastEventId.current) return;
          lastEventId.current = eventId;
        }
        if (payload.resync) {
          recoveryPending.current = true;
          inboxRevision.current += 1;
          const selectedChat = current.current.selectedChat;
          if (selectedChat) {
            const key = conversationKey(selectedChat.id, selectedChat.type);
            eventRevision.current.set(key, (eventRevision.current.get(key) || 0) + 1);
          }
          void recover({ refreshInbox: true }).catch(() => {});
          return;
        }
        if (!payload.conversation_id) {
          recoveryPending.current = true;
          void recover({ refreshInbox: true }).catch(() => {});
          return;
        }

        const id = Number(payload.conversation_id);
        const type = payload.conversation_type || "conversation";
        const key = conversationKey(id, type);
        eventRevision.current.set(key, (eventRevision.current.get(key) || 0) + 1);
        if (payload.summary) applySummary(type, id, payload.summary);
        else inboxRevision.current += 1;

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
            // The admin receipt represents both participants; reconcile from
            // the server rather than guessing which participant read first.
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

        const state = pending.current.get(key) || {
          conversation_id: id,
          conversation_type: type,
          deleted_message_ids: new Set(),
          refresh_messages: false,
        };
        if (payload.action === "delete" && payload.message_id) {
          state.deleted_message_ids.add(Number(payload.message_id));
        }
        // Read events also request an incremental status reconcile. This heals
        // races with a concurrent send/read and keeps MessageBubble authoritative.
        if (payload.action !== "delete") {
          state.refresh_messages = true;
        }
        pending.current.set(key, state);
        if (syncing.current && isSameChat(current.current.selectedChat, id, type)) {
          syncQueued.current = true;
        }
        void flush();
      });
    } else {
      // One-shot reconciliation is safer than introducing a polling loop.
      void recover().catch(() => {});
    }

    const onVisibilityChange = () => {
      if (document.visibilityState !== "visible") return;
      if (recoveryPending.current) void recover({ refreshInbox: true }).catch(() => {});
      else void syncSelected().catch(() => {});
    };
    document.addEventListener("visibilitychange", onVisibilityChange);
    return () => {
      active = false;
      pending.current.clear();
      source?.close();
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
  }, [auth, request]);
}
