import { createEffect } from "solid-js";
import { getInboxData } from "../../../shared/services/panelApi.js";
import { subscribePanelEvents } from "../../../shared/services/panelEventStream.js";
import { acknowledgeChatMessages, syncChatState } from "../services/conversationsApi.js";
import { markConversationMessageDeleted, mergeConversationMessages } from "../services/messageState.js";
import { mergeInboxSnapshot } from "../../../shared/services/inboxState.js";
import { hasSummaryChanges, requiresMessageSync } from "../services/conversationEventPolicy.js";
const maxMessageId = (rows) => rows.reduce((max, row) => Math.max(max, Number(row.id) || 0), 0);
const isSameChat = (chat, id, type) =>
  Number(chat?.id) === Number(id) && (chat?.type === "personal") === (type === "personal");
const conversationKey = (id, type) => (type === "personal" ? "personal:" : "conversation:") + id;
export function createConversationSync(options) {
  let resumeSelected = () => {};
  let acknowledgeVisible = () => {};
  createEffect(
    () => [options.auth, options.request],
    () => {
      if (!options.auth) return undefined;
      let active = true;
      let lastMessageCursor = { chatKey: "", id: 0 };
      let lastEventId = 0;
      const pending = new Map();
      let processing = false;
      let flushTimer = 0;
      let syncing = false;
      let syncQueued = false;
      const eventRevision = new Map();
      let inboxRequestRevision = 0;
      let recoveryPending = false;
      const applySummary = (type, id, summary) => {
        if (!summary || !active) return;
        const rowKey = conversationKey(id, type);
        options.inboxRowRevision.set(rowKey, (options.inboxRowRevision.get(rowKey) || 0) + 1);
        const setList = type === "personal" ? options.setPersonalChats : options.setChats;
        setList((items) => {
          const existing = items.find((item) => Number(item.id) === Number(id));
          if (!existing) return [summary, ...items];
          if (!hasSummaryChanges(existing, summary)) return items;
          return items.map((item) =>
            Number(item.id) === Number(id) ? { ...item, ...summary } : item,
          );
        });
        options.setSelectedChat((previous) =>
          isSameChat(previous, id, type) && hasSummaryChanges(previous, summary)
            ? { ...previous, ...summary }
            : previous,
        );
      };
      let receiptChatKey = "";
      let receipts = new Set();
      acknowledgeVisible = async (chat, visibleIds) => {
        if (!options.activeChat || !isSameChat(options.activeChat, chat.id, chat.type)) return;
        const key = conversationKey(chat.id, chat.type);
        if (receiptChatKey !== key) {
          receiptChatKey = key;
          receipts = new Set();
        }
        const requested = receipts;
        const ids = visibleIds.filter(id => !requested.has(id)).slice(0, 500);
        if (!ids.length) return;
        for (const id of ids) requested.add(id);
        const revision = options.inboxRowRevision.get(key) || 0;
        try {
          const summary = await acknowledgeChatMessages(options.request, chat, ids);
          if (revision === (options.inboxRowRevision.get(key) || 0) && summary?.id === chat.id) {
            applySummary(chat.type, chat.id, summary);
          }
        } catch (error) {
          for (const id of ids) requested.delete(id);
          throw error;
        }
      };
      const refreshInbox = async () => {
        const requestRevision = ++inboxRequestRevision;
        const revisionsAtStart = new Map(options.inboxRowRevision);
        const [conversations, personal] = await getInboxData(options.request);
        if (!active || requestRevision !== inboxRequestRevision) return;
        const selected = options.selectedChat;
        if (selected && !(selected.type === "personal" ? personal : conversations).some(row => row.id === selected.id)) {
          options.setSelectedChat(null);
          options.setMessages([]);
        }
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
        if (!options.foregroundChat) return;
        if (syncing) {
          syncQueued = true;
          return;
        }
        syncing = true;
        try {
          do {
            syncQueued = false;
            const chat = options.foregroundChat;
            if (!chat) break;
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
            const summaryRevision = options.inboxRowRevision.get(chatKey) || 0;
            const result = await syncChatState(options.request, chat, afterId, knownIds);
            if (!active) break;
            if (!isSameChat(options.foregroundChat, chat.id, chat.type)) {
              syncQueued = true;
              continue;
            }

            // Новое событие уже пришло: старый ответ запроса игнорируем.
            if (revisionAtStart !== (eventRevision.get(chatKey) || 0)) {
              syncQueued = true;
              continue;
            }
            if (result.deleted_message_ids?.length) {
              const deleted = new Set(result.deleted_message_ids);
              for (const id of deleted) {
                markConversationMessageDeleted(chatKey, id);
                options.cache.removeMessage(chatKey, id);
              }
              options.setMessages(rows => rows.filter(row => !deleted.has(Number(row.id))));
            }
            const updated = [...(result.updated_messages || []), ...(result.messages || [])];
            if (updated.length) {
              lastMessageCursor.id = Math.max(afterId, maxMessageId(updated));
              options.setMessages((previous) => mergeConversationMessages(previous, updated, chatKey));
            }
            if (result.has_more) syncQueued = true;
            if (summaryRevision === (options.inboxRowRevision.get(chatKey) || 0)) {
              applySummary(chat.type, chat.id, result.summary);
            }
          } while (syncQueued && active);
        } finally {
          syncing = false;
          if (syncQueued && active && options.foregroundChat) {
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
      const requestRecovery = () => {
        recoveryPending = true;
        void recover({ refreshInbox: true }).catch(() => {});
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
          requestRecovery();
        } finally {
          processing = false;
          if (pending.size && active) void flush();
        }
      };
      const scheduleFlush = () => {
        if (flushTimer || !active) return;
        flushTimer = setTimeout(() => {
          flushTimer = 0;
          void flush();
        }, 35);
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
          if (!payload.resync && eventId <= lastEventId) return;
          lastEventId = eventId;
        }
        if (payload.resync) {
          const selectedChat = options.selectedChat;
          options.cache.clearInactiveHistories(selectedChat ? conversationKey(selectedChat.id, selectedChat.type) : "");
          if (selectedChat) {
            const key = conversationKey(selectedChat.id, selectedChat.type);
            eventRevision.set(key, (eventRevision.get(key) || 0) + 1);
          }
          requestRecovery();
          return;
        }
        if (!payload.conversation_id) {
          requestRecovery();
          return;
        }
        const id = Number(payload.conversation_id);
        const type = payload.conversation_type || "conversation";
        const key = conversationKey(id, type);
        eventRevision.set(key, (eventRevision.get(key) || 0) + 1);
        if (payload.summary) applySummary(type, id, payload.summary);
        else {
          requestRecovery();
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
          } else if (expectedReader === payload.actor_role || viewerRole === payload.actor_role) {
            const readIds = new Set(payload.message_ids.map(Number));
            const readAt = payload.read_at || new Date().toISOString();
            options.setMessages((rows) => {
              let changed = false;
              const next = rows.map((row) => {
                if (!readIds.has(Number(row.id))) return row;
                if (type !== "personal" && row.sender_role === "admin") {
                  const field = payload.actor_role + "_read_at";
                  if (row.metadata?.[field]) return row;
                  const metadata = { ...row.metadata, [field]: readAt };
                  changed = true;
                  return { ...row, metadata, panel_read_at: metadata.teacher_read_at && metadata.student_read_at || null };
                }
                if (row.panel_read_at) return row;
                changed = true;
                return { ...row, panel_read_at: readAt };
              });
              return changed ? next : rows;
            });
          }
        }
        // Read receipts are already reflected in the summary and outgoing bubbles.
        // Only the admin participant view needs a full status refresh.
        if (payload.action === "delete" && payload.message_id) {
          markConversationMessageDeleted(key, Number(payload.message_id));
          options.cache.removeMessage(key, Number(payload.message_id));
        }
        if (!isSameChat(selected, id, type) || !requiresMessageSync(payload.action, viewerRole, type)) return;
        const state = pending.get(key) || {
          conversation_id: id,
          conversation_type: type,
          conversation_key: key,
          deleted_message_ids: new Set(),
          refresh_messages: false,
        };
        if (payload.action === "delete" && payload.message_id) {
          state.deleted_message_ids.add(Number(payload.message_id));
        }
        if (payload.action !== "delete") state.refresh_messages = true;
        pending.set(key, state);
        if (syncing && isSameChat(options.selectedChat, id, type)) {
          syncQueued = true;
        }
        scheduleFlush();
      };
      const unsubscribe = subscribePanelEvents(handleEvent, () => {
        if (recoveryPending) {
          void recover({
            refreshInbox: true,
          }).catch(() => {});
        } else {
          void syncSelected().catch(() => {});
        }
      }, () => {
        recoveryPending = true;
        void Promise.resolve(options.verifySession?.()).catch(() => {});
      });
      if (!unsubscribe) requestRecovery();
      // Reconcile even if an apparently healthy stream silently loses a hint.
      // No automatic read receipts; no full history reload.
      let checking = false;
      const fallback = setInterval(async () => {
        if (!active || checking || document.visibilityState !== "visible") return;
        checking = true;
        try { await recover({ refreshInbox: true }); } catch { /* retry next interval */ }
        finally { checking = false; }
      }, 30000);
      resumeSelected = () => {
        if (document.visibilityState !== "visible") return;
        if (recoveryPending)
          void recover({
            refreshInbox: true,
          }).catch(() => {});
        else void syncSelected().catch(() => {});
      };
      const onForeground = () => resumeSelected();
      document.addEventListener("visibilitychange", onForeground);
      window.addEventListener("focus", onForeground);
      return () => {
        active = false;
        clearTimeout(flushTimer);
        clearInterval(fallback);
        pending.clear();
        unsubscribe?.();
        document.removeEventListener("visibilitychange", onForeground);
        window.removeEventListener("focus", onForeground);
        resumeSelected = () => {};
        acknowledgeVisible = () => {};
      };
    },
  );
  createEffect(
    () => [options.inDialogs],
    ([inDialogs]) => {
      if (inDialogs) resumeSelected();
    },
  );
  return (chat, ids) => acknowledgeVisible(chat, ids);
}
