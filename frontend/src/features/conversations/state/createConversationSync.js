import { createEffect } from "solid-js";
import { getInboxData } from "../../../shared/services/panelApi.js";
import { subscribePanelEvents } from "../../../shared/services/panelEventStream.js";
import { acknowledgeChatMessages, syncChatState } from "../services/conversationsApi.js";
import { markConversationMessageDeleted, mergeConversationMessages } from "../services/messageState.js";
import { mergeInboxSnapshot } from "../../../shared/services/inboxState.js";
import { applyDeliveryStatus, applyReadReceipt, hasSummaryChanges, requiresMessageSync } from "../services/conversationEventPolicy.js";
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
      let syncing = false;
      let syncQueued = false;
      let reconcileKnown = false;
      let rewind = null;
      let inFlight = null;
      const eventRevision = new Map();
      let inboxRequestRevision = 0;
      let recoveryPending = false;
      let streamUnavailable = false;
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
        const changedRows = new Set(
          [...options.inboxRowRevision]
            .filter(([key, revision]) => revision > (revisionsAtStart.get(key) || 0))
            .map(([key]) => key),
        );
        if (selected && !changedRows.has(conversationKey(selected.id, selected.type)) &&
            !(selected.type === "personal" ? personal : conversations).some(row => row.id === selected.id)) {
          options.setSelectedChat(null);
          options.setMessages([]);
        }
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
      const syncSelected = async ({ full = true, force = false, beforeGap = null } = {}) => {
        const selected = options.selectedDialog;
        if (!selected) return;
        const requestedKey = conversationKey(selected.id, selected.type);
        if (beforeGap !== null) {
          rewind = {
            key: requestedKey,
            id: rewind?.key === requestedKey ? Math.min(rewind.id, beforeGap) : beforeGap,
          };
          force = true;
        }
        if (syncing) {
          // A concurrent trigger for the same revision is covered by this request.
          if (force || (full && !inFlight?.full) || inFlight?.key !== requestedKey ||
              inFlight.revision !== (eventRevision.get(requestedKey) || 0)) {
            syncQueued = true;
            reconcileKnown ||= full;
          }
          return;
        }
        reconcileKnown ||= full;
        syncing = true;
        try {
          do {
            syncQueued = false;
            const chat = options.selectedDialog;
            if (!chat) break;
            const chatKey = conversationKey(chat.id, chat.type);
            const checkKnown = reconcileKnown;
            reconcileKnown = false;
            const knownIds = [];
            let afterId = lastMessageCursor.chatKey === chatKey ? lastMessageCursor.id : 0;
            for (const message of options.messages) {
              const id = Number(message.id);
              if (Number.isSafeInteger(id) && id > 0) {
                if (checkKnown) knownIds.push(id);
                afterId = Math.max(afterId, id);
              }
            }
            if (rewind?.key === chatKey) {
              afterId = Math.min(afterId, rewind.id);
              rewind = null;
            }
            lastMessageCursor = {
              chatKey,
              id: afterId,
            };
            const revisionAtStart = eventRevision.get(chatKey) || 0;
            inFlight = { key: chatKey, revision: revisionAtStart, full: checkKnown };
            const summaryRevision = options.inboxRowRevision.get(chatKey) || 0;
            const result = await syncChatState(options.request, chat, afterId, knownIds);
            if (!active) break;
            if (!isSameChat(options.selectedDialog, chat.id, chat.type)) {
              syncQueued = true;
              reconcileKnown = true;
              continue;
            }

            // Never replace newer receipt/summary data with a stale response.
            // New immutable rows are still useful and tombstones suppress any
            // message deleted by an intervening event.
            const changedDuringRequest = revisionAtStart !== (eventRevision.get(chatKey) || 0);
            if (changedDuringRequest) {
              const fresh = result.messages || [];
              if (fresh.length) {
                options.setMessages(previous => {
                  const existing = new Set(previous.map(row => String(row.id)));
                  return mergeConversationMessages(previous, fresh.filter(row => !existing.has(String(row.id))), chatKey);
                });
              }
              syncQueued = true;
              reconcileKnown ||= checkKnown;
              // Retry a rewind rather than jumping over a missing message.
              rewind = { key: chatKey, id: rewind?.key === chatKey ? Math.min(rewind.id, afterId) : afterId };
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
          inFlight = null;
          if (syncQueued && active && options.selectedDialog) {
            void syncSelected({ full: reconcileKnown }).catch(() => { recoveryPending = true; });
          }
        }
      };
      let recovery = null;
      const recover = () => {
        if (!active) return Promise.resolve();
        recoveryPending = true;
        if (recovery) return recovery;
        recovery = (async () => {
          try {
            while (active && recoveryPending) {
              recoveryPending = false;
              await refreshInbox();
              if (active) await syncSelected({ force: true });
            }
          } catch (error) {
            recoveryPending = true;
            throw error;
          } finally {
            recovery = null;
          }
        })();
        return recovery;
      };
      const requestRecovery = () => { void recover().catch(() => {}); };
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
          // A restart/restore can replace the server cursor range (clock rollback).
          // Explicit resync is always authoritative, even for a smaller cursor.
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
        // Non-admin delivery is invisible and must not invalidate an in-flight sync.
        if (payload.action === "delivery" && options.role !== "admin") return;
        eventRevision.set(key, (eventRevision.get(key) || 0) + 1);
        if (payload.summary) applySummary(type, id, payload.summary);
        else if (payload.action !== "delivery") {
          requestRecovery();
        }
        const selected = options.selectedChat;
        const viewerRole = options.role;
        if (payload.action === "read" && isSameChat(selected, id, type)) {
          options.setMessages(rows => applyReadReceipt(rows, payload, type));
        }
        if (payload.action === "delete" && payload.message_id) {
          const messageId = Number(payload.message_id);
          markConversationMessageDeleted(key, messageId);
          options.cache.removeMessage(key, messageId);
          if (isSameChat(selected, id, type)) {
            options.setMessages(rows => rows.filter(row => Number(row.id) !== messageId));
          }
          return;
        }
        if (payload.action === "delivery" && payload.message_status && isSameChat(selected, id, type)) {
          options.setMessages(rows => applyDeliveryStatus(rows, payload.message_status,
            (previous, updates) => mergeConversationMessages(previous, updates, key)));
        }
        if (!isSameChat(selected, id, type)) return;
        // A complete, authorized message can be rendered without a second HTTP
        // request. During recovery keep the cursor unchanged and reconcile gaps.
        const message = payload.message;
        let beforeGap = null;
        if (payload.action === "upsert" && message && Number(message.id) === Number(payload.message_id)) {
          const previousId = Number(payload.previous_message_id) || 0;
          const rows = options.messages;
          const hasPredecessor = !previousId || rows.some(row =>
            Number(row.id) === previousId || Number(row.id) === Number(message.id));
          if (hasPredecessor && !syncing && !recovery && !recoveryPending) {
            options.setMessages(previous => mergeConversationMessages(previous, [message], key));
            return;
          }
          if (!hasPredecessor) {
            beforeGap = rows.reduce((cursor, row) => {
              const id = Number(row.id);
              return id > 0 && id < previousId ? Math.max(cursor, id) : cursor;
            }, 0);
          }
        }
        if (!requiresMessageSync(payload.action, viewerRole, type, payload.message_status)) return;
        // Start fetching in the SSE callback itself. Background-tab timer
        // throttling must never delay an incoming message. syncSelected already
        // serializes requests and coalesces events arriving during a fetch.
        // Ordinary upserts only need messages after the cursor. Reconcile
        // existing statuses on recovery or a specific status invalidation.
        void syncSelected({ full: payload.action !== "upsert", beforeGap }).catch(requestRecovery);
      };
      const reconcileSelected = () => {
        void syncSelected().catch(() => { recoveryPending = true; });
      };
      const unsubscribe = subscribePanelEvents(handleEvent, () => {
        const needsRecovery = streamUnavailable || recoveryPending;
        streamUnavailable = false;
        if (needsRecovery) requestRecovery();
        else reconcileSelected();
      }, () => {
        const firstError = !streamUnavailable;
        streamUnavailable = true;
        recoveryPending = true;
        if (firstError) void Promise.resolve(options.verifySession?.()).catch(() => {});
      });
      if (!unsubscribe) {
        streamUnavailable = true;
        requestRecovery();
      }
      // SSE remains the fast path. An infrequent reconciliation also covers
      // suspended browsers, missed events and intermediaries buffering the stream.
      let lastReconciliation = Date.now();
      const fallback = setInterval(() => {
        if (!active) return;
        // Recover quickly if streaming is unavailable, otherwise only perform
        // an infrequent safety check. Reading remains independently gated.
        if (streamUnavailable || recoveryPending || Date.now() - lastReconciliation >= 60000) {
          lastReconciliation = Date.now();
          requestRecovery();
        }
      }, 5000);
      resumeSelected = () => {
        if (document.visibilityState !== "visible") return;
        if (recoveryPending) requestRecovery();
        else reconcileSelected();
      };
      const onForeground = () => resumeSelected();
      document.addEventListener("visibilitychange", onForeground);
      window.addEventListener("focus", onForeground);
      return () => {
        active = false;
        clearInterval(fallback);
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
