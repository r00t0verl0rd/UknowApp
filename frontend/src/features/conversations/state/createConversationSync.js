import { createEffect } from "solid-js";
import { getInboxData } from "../../../shared/services/panelApi.js";
import { subscribePanelEvents } from "../../../shared/services/panelEventStream.js";
import { syncChatState } from "../services/conversationsApi.js";
import { markConversationMessageDeleted, mergeConversationMessages } from "../services/messageState.js";
import { mergeInboxSnapshot } from "../../../shared/services/inboxState.js";
const maxMessageId = (rows) => rows.reduce((max, row) => Math.max(max, Number(row.id) || 0), 0);
const isSameChat = (chat, id, type) =>
  Number(chat?.id) === Number(id) && (chat?.type === "personal") === (type === "personal");
const conversationKey = (id, type) => (type === "personal" ? "personal:" : "conversation:") + id;
export function createConversationSync(options) {
  let lastMessageCursor = { chatKey: "", id: 0 };
  let lastEventId = 0;
  const pending = new Map();
  let processing = false;
  let syncing = false;
  let syncQueued = false;
  const eventRevision = new Map();
  let inboxRequestRevision = 0;
  let recoveryPending = false;
  createEffect(
    () => [options.auth, options.request],
    () => {
      if (!options.auth) return undefined;
      let active = true;
      const applySummary = (type, id, summary) => {
        if (!summary || !active) return;
        const rowKey = conversationKey(id, type);
        options.inboxRowRevision.set(rowKey, (options.inboxRowRevision.get(rowKey) || 0) + 1);
        if (type === "personal") {
          options.setPersonalChats((items) =>
            items.some((item) => Number(item.id) === Number(id))
              ? items.map((item) =>
                  Number(item.id) === Number(id)
                    ? {
                        ...item,
                        ...summary,
                      }
                    : item,
                )
              : [summary, ...items],
          );
        } else {
          options.setChats((items) =>
            items.some((item) => Number(item.id) === Number(id))
              ? items.map((item) =>
                  Number(item.id) === Number(id)
                    ? {
                        ...item,
                        ...summary,
                      }
                    : item,
                )
              : [summary, ...items],
          );
        }
        options.setSelectedChat((previous) =>
          isSameChat(previous, id, type)
            ? {
                ...previous,
                ...summary,
              }
            : previous,
        );
      };
      const refreshInbox = async () => {
        const requestRevision = ++inboxRequestRevision;
        const revisionsAtStart = new Map(options.inboxRowRevision);
        const [conversations, personal] = await getInboxData(options.request);
        if (!active || requestRevision !== inboxRequestRevision) return;
        const changedRows = new Set(
          [...options.inboxRowRevision]
            .filter(([key, revision]) => revision > (revisionsAtStart.get(key) || 0))
            .map(([key]) => key),
        );
        const changedConversations = new Set(
          [...changedRows]
            .filter((key) => key.startsWith("conversation:"))
            .map((key) => Number(key.slice("conversation:".length))),
        );
        const changedPersonal = new Set(
          [...changedRows]
            .filter((key) => key.startsWith("personal:"))
            .map((key) => Number(key.slice("personal:".length))),
        );
        options.setChats((items) => mergeInboxSnapshot(conversations, items, changedConversations));
        options.setPersonalChats((items) => mergeInboxSnapshot(personal, items, changedPersonal));
      };
      const syncSelected = async () => {
        if (document.visibilityState !== "visible") return;
        if (syncing) {
          syncQueued = true;
          return;
        }
        syncing = true;
        try {
          do {
            syncQueued = false;
            const chat = options.selectedChat;
            if (!chat || document.visibilityState !== "visible") break;
            const chatKey = conversationKey(chat.id, chat.type);
            const knownIds = [];
            let afterId = lastMessageCursor.chatKey === chatKey ? lastMessageCursor.id : 0;
            for (const message of options.messages) {
              const id = Number(message.id);
              if (Number.isSafeInteger(id) && id > 0) {
                knownIds.push(id);
                afterId = Math.max(afterId, id);
              }
            }
            lastMessageCursor = {
              chatKey,
              id: afterId,
            };
            const revisionAtStart = eventRevision.get(chatKey) || 0;
            const result = await syncChatState(options.request, chat, afterId, knownIds);
            if (!active) break;
            if (!isSameChat(options.selectedChat, chat.id, chat.type)) {
              syncQueued = true;
              continue;
            }

            // Новое событие уже пришло: старый ответ запроса игнорируем.
            if (revisionAtStart !== (eventRevision.get(chatKey) || 0)) {
              syncQueued = true;
              continue;
            }
            const updated = [...(result.updated_messages || []), ...(result.messages || [])];
            if (updated.length) {
              lastMessageCursor.id = Math.max(afterId, maxMessageId(updated));
              options.setMessages((previous) => mergeConversationMessages(previous, updated, chatKey));
            }
            if (result.summary) applySummary(chat.type, chat.id, result.summary);
          } while (syncQueued && active);
        } finally {
          syncing = false;
          if (syncQueued && active && document.visibilityState === "visible") {
            void syncSelected().catch(() => {});
          }
        }
      };
      const recover = async ({ refreshInbox: refresh = false } = {}) => {
        try {
          if (refresh) await refreshInbox();
          await syncSelected();
          recoveryPending = false;
        } catch (error) {
          recoveryPending = true;
          throw error;
        }
      };
      const flush = async () => {
        if (processing || !active) return;
        processing = true;
        try {
          while (pending.size && active) {
            const events = [...pending.values()];
            pending.clear();
            await Promise.all(
              events.map(async (event) => {
                const {
                  conversation_id: id,
                  conversation_type: type,
                  conversation_key: key,
                  deleted_message_ids: deletedIds,
                  refresh_messages: refreshMessages,
                } = event;
                const chat = options.selectedChat;
                if (isSameChat(chat, id, type)) {
                  if (deletedIds.size) {
                    for (const messageId of deletedIds) markConversationMessageDeleted(key, messageId);
                    options.setMessages((rows) => rows.filter((row) => !deletedIds.has(Number(row.id))));
                  }
                  if (refreshMessages) await syncSelected();
                }
              }),
            );
          }
        } catch {
          // Курсор сдвинулся: запрашиваем сверку с сервером.
          recoveryPending = true;
          void recover({
            refreshInbox: true,
          }).catch(() => {});
        } finally {
          processing = false;
          if (pending.size && active) void flush();
        }
      };
      const handleEvent = (event) => {
        let payload;
        try {
          payload = JSON.parse(event.data || "{}");
        } catch {
          payload = {
            resync: true,
          };
        }
        const eventId = Number(payload.event_id || event.lastEventId || 0);
        if (Number.isSafeInteger(eventId) && eventId > 0) {
          if (eventId <= lastEventId) return;
          lastEventId = eventId;
        }
        if (payload.resync) {
          recoveryPending = true;
          const selectedChat = options.selectedChat;
          if (selectedChat) {
            const key = conversationKey(selectedChat.id, selectedChat.type);
            eventRevision.set(key, (eventRevision.get(key) || 0) + 1);
          }
          void recover({
            refreshInbox: true,
          }).catch(() => {});
          return;
        }
        if (!payload.conversation_id) {
          recoveryPending = true;
          void recover({
            refreshInbox: true,
          }).catch(() => {});
          return;
        }
        const id = Number(payload.conversation_id);
        const type = payload.conversation_type || "conversation";
        const key = conversationKey(id, type);
        eventRevision.set(key, (eventRevision.get(key) || 0) + 1);
        if (payload.summary) applySummary(type, id, payload.summary);
        else {
          recoveryPending = true;
          void recover({
            refreshInbox: true,
          }).catch(() => {});
        }
        const selected = options.selectedChat;
        const viewerRole = options.role;
        const expectedReader =
          selected?.type === "personal"
            ? viewerRole === "admin"
              ? selected.participant?.role
              : "admin"
            : viewerRole === "teacher"
              ? "student"
              : viewerRole === "student"
                ? "teacher"
                : null;
        if (
          payload.action === "read" &&
          isSameChat(selected, id, type) &&
          Array.isArray(payload.message_ids) &&
          payload.message_ids.length
        ) {
          if (viewerRole === "admin" && type !== "personal") {
            // Администратор видит статусы обоих участников.
          } else if (expectedReader === payload.actor_role) {
            const readIds = new Set(payload.message_ids.map(Number));
            const readAt = payload.read_at || new Date().toISOString();
            options.setMessages((rows) =>
              rows.map((row) =>
                readIds.has(Number(row.id)) && row.sender_role === viewerRole && !row.panel_read_at
                  ? {
                      ...row,
                      panel_read_at: readAt,
                    }
                  : row,
              ),
            );
          }
        }
        const state = pending.get(key) || {
          conversation_id: id,
          conversation_type: type,
          conversation_key: key,
          deleted_message_ids: new Set(),
          refresh_messages: false,
        };
        if (payload.action === "delete" && payload.message_id) {
          state.deleted_message_ids.add(Number(payload.message_id));
          markConversationMessageDeleted(key, payload.message_id);
        }
        if (payload.action !== "delete") state.refresh_messages = true;
        pending.set(key, state);
        if (syncing && isSameChat(options.selectedChat, id, type)) {
          syncQueued = true;
        }
        void flush();
      };
      const unsubscribe = subscribePanelEvents(handleEvent, () => {
        if (recoveryPending) {
          void recover({
            refreshInbox: true,
          }).catch(() => {});
        } else {
          void syncSelected().catch(() => {});
        }
      });
      if (!unsubscribe) {
        // Единичная сверка безопаснее постоянного polling.
        void recover().catch(() => {});
      }
      const onVisibilityChange = () => {
        if (document.visibilityState !== "visible") return;
        if (recoveryPending)
          void recover({
            refreshInbox: true,
          }).catch(() => {});
        else void syncSelected().catch(() => {});
      };
      document.addEventListener("visibilitychange", onVisibilityChange);
      return () => {
        active = false;
        pending.clear();
        unsubscribe?.();
        document.removeEventListener("visibilitychange", onVisibilityChange);
      };
    },
  );
}
