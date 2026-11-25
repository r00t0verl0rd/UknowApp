import { createSignal, createMemo, createEffect } from "solid-js";
import { createChatActionState } from "./createChatActionState.js";
import { viewAccountKey, persistentViewValue, savePersistentViewValue, readScrollPositions, saveViewPreference, viewPreference } from "../../../shared/services/viewSession.js";
import { markConversationMessageDeleted, mergeConversationMessages } from "../services/messageState.js";
import {
  createPersonalConversation,
  deleteChatMessage,
  deletePersonalConversation,
  getChatMessages,
  getChatWindow,
  HISTORY_PAGE_SIZE,
  sendConversationAttachment,
  sendConversationText,
  sendPersonalMessage,
  syncChatState,
} from "../services/conversationsApi.js";
export function createChatsController(options) {
  const actions = createChatActionState();
  const [creating, setCreating] = createSignal(false);
  const cache = options.chatState.cache;
  const selected = options.chatState.selectedChat;
  const initialKey = selected ? (selected.type === "personal" ? "personal:" : "conversation:") + selected.id : "";
  const [olderCursor, setOlderCursor] = createSignal(cache.getHistory(initialKey)?.olderCursor || 0);
  const [loadingOlder, setLoadingOlder] = createSignal(false);
  let olderRequest;
  let sendingMessage = false;
  let pendingClientMessage = null;
  let openingChatRequest = null;
  let attemptedRestoreForUser = null;
  const [positionedKey, setPositionedKey] = createSignal("");
  const [showLatest, setShowLatest] = createSignal(false);
  createEffect(
    () => [],
    () => () => openingChatRequest?.controller.abort(),
  );
  const activeChatKey = () =>
    options.chatState.selectedChat
      ? (options.chatState.selectedChat.type === "personal" ? "personal:" : "conversation:") +
        options.chatState.selectedChat.id
      : "";
  createEffect(
    () => [
      options.auth,
      options.profile,
      options.personalState.personalChats,
      options.chatState.chats,
      options.personalState.setChatSection,
    ],
    () => {
      if (!options.auth || !options.profile) return;
      const params = new URLSearchParams(window.location.search);
      const conversationId = Number(params.get("openConversation"));
      if (!conversationId) return;
      const personal = params.get("type") === "personal";
      const source = personal ? options.personalState.personalChats : options.chatState.chats;
      const chat = source.find((item) => Number(item.id) === conversationId);
      if (!chat) return;
      window.history.replaceState({}, "", window.location.pathname + window.location.hash);
      if (personal) options.personalState.setChatSection("personal");
      void openChat(chat);
    },
  );
  // Обновляем кэш уже показанной переписки при ответе сервера и SSE.
  // Это важно на телефоне: кнопка «Назад» очищает открытый чат, но
  // возвращение к нему не должно ждать повторной загрузки истории.
  createEffect(
    () => [activeChatKey(), options.chatState.messages, options.chatState.messagesLoading, olderCursor()],
    ([key, messages, loading, cursor]) => {
      if (key && !loading) cache.saveHistory(key, messages, cursor);
    },
  );
  const visibleMessages = createMemo(() => {
    if (options.chatState.messageFilter === "all") return options.chatState.messages;
    return options.chatState.messages.filter((message) => {
      const kind = message.metadata?.media?.kind || message.content_type;
      if (options.chatState.messageFilter === "media")
        return kind !== "text" || Boolean(message.metadata?.media);
      if (options.chatState.messageFilter === "audio") return ["voice", "audio"].includes(kind);
      if (options.chatState.messageFilter === "photos") return kind === "photo";
      if (options.chatState.messageFilter === "files")
        return [
          "document",
          "video",
          "video_note",
          "video_sticker",
          "animation",
          "animated_sticker",
          "sticker",
        ].includes(kind);
      return true;
    });
  });
  const visibleChats = createMemo(() => {
    const query = options.chatState.chatSearch.trim().toLocaleLowerCase("ru");
    const personal = options.personalState.personalChats.filter(
      (chat) =>
        (!query || chat.title.toLocaleLowerCase("ru").includes(query)) &&
        (options.chatState.chatFilter === "all" || Number(chat.unread_count || 0) > 0),
    );
    const regular =
      options.profile?.role === "student"
        ? options.chatState.chats.slice(0, 1)
        : options.chatState.chats.filter((chat) => {
            const names =
              options.profile?.role === "admin"
                ? chat.teacher.full_name + " " + chat.student.full_name
                : chat.student.full_name + " " + chat.teacher.full_name;
            const matchesSearch = !query || names.toLocaleLowerCase("ru").includes(query);
            const matchesFilter =
              options.profile?.role !== "teacher" ||
              options.chatState.chatFilter === "all" ||
              Number(chat.unread_count || 0) > 0;
            return matchesSearch && matchesFilter;
          });
    const rows =
      options.profile?.role === "admin"
        ? options.personalState.chatSection === "personal"
          ? personal
          : regular
        : [...regular, ...personal];
    return rows.sort(
      (a, b) =>
        Number(b.unread_count > 0) - Number(a.unread_count > 0) ||
        (b.last_message_at || b.created_at || "").localeCompare(a.last_message_at || a.created_at || "") ||
        b.id - a.id,
    );
  });
  let unreadAnchor = null;
  let capturePosition = () => {};
  let schedulePosition = () => {};
  let requestLatestScroll = () => {};
  const positionName = (key, filter) => `messages:${key}${filter === "all" ? "" : ":" + filter}`;
  const savedPosition = (key, filter) => {
    const name = positionName(key, filter);
    return persistentViewValue(viewAccountKey(options.profile), name, readScrollPositions(viewAccountKey(options.profile), "chats")[name]);
  };
  createEffect(
    () => [
      options.chatState.selectedChat?.id,
      options.chatState.selectedChat?.type,
      options.chatState.messageFilter,
      options.chatState.messagesViewportRef.current,
    ],
    () => {
      const history = options.chatState.messagesViewportRef.current;
      const key = activeChatKey();
      if (!history || !key) return;
      const filter = options.chatState.messageFilter;
      const name = positionName(key, filter);
      const userId = viewAccountKey(options.profile);
      const saved = savedPosition(key, filter);
      let position = saved;
      let initialized = false;
      let followBottom = false;
      let forced = false;
      let frame = 0;
      let captureTimer = 0;
      let appliedTop = null;
      const current = () => history.isConnected && history.clientHeight > 0 &&
        history.dataset.viewScrollKey === key && activeChatKey() === key &&
        options.chatState.messageFilter === filter;
      const distanceToLatest = () => Math.max(0,
        history.scrollHeight - history.scrollTop - history.clientHeight);
      const findRow = id => /^message:\d+$/.test(id || "") &&
        history.querySelector(`[data-view-anchor="${id}"]`);
      const readPosition = () => {
        const bounds = history.getBoundingClientRect();
        const rows = history.children;
        let low = 0;
        let high = rows.length;
        while (low < high) {
          const mid = (low + high) >>> 1;
          if (rows[mid].getBoundingClientRect().bottom <= bounds.top) low = mid + 1;
          else high = mid;
        }
        const row = rows[low]?.dataset.viewAnchor ? rows[low] : rows[low + 1];
        const id = row?.dataset.viewAnchor;
        if (!/^message:\d+$/.test(id || "")) return null;
        return {
          top: Math.max(0, history.scrollTop),
          bottom: followBottom,
          anchor: { id, offset: row.getBoundingClientRect().top - bounds.top },
        };
      };
      const persist = () => {
        if (initialized && position) savePersistentViewValue(userId, name, position);
      };
      const capture = () => {
        if (initialized && current()) {
          // Do not replace the stable anchor with a temporary geometry change.
          // Scroll events update it when the user actually moves.
          if (appliedTop === null || Math.abs(history.scrollTop - appliedTop) > 1) {
            followBottom = distanceToLatest() <= 24;
            position = readPosition() || position;
            appliedTop = history.scrollTop;
          }
        }
        persist();
      };
      const apply = () => {
        frame = 0;
        if (!current()) return;
        if (!initialized) {
          const request = openingChatRequest?.key === key ? openingChatRequest : null;
          const row = findRow(saved?.anchor?.id);
          // A validated cache containing the saved anchor (or the latest page)
          // may render immediately. Otherwise wait for the requested window.
          const cachedPositionReady = request?.hasCache &&
            (!saved || saved.bottom === true || row);
          if (request && !request.windowReady && !cachedPositionReady) return;
          if (options.chatState.messagesLoading && !request) return;
          const unreadRow = unreadAnchor?.key === key &&
            findRow("message:" + unreadAnchor.id);
          if (forced || saved?.bottom === true || (!saved && !unreadRow)) {
            followBottom = true;
            history.scrollTop = history.scrollHeight;
          } else if (saved) {
            history.scrollTop = row ? history.scrollTop + row.getBoundingClientRect().top -
              history.getBoundingClientRect().top - (saved.anchor.offset || 0) : saved.top;
            // Older persisted positions did not have an explicit bottom flag.
            followBottom = saved.bottom == null && distanceToLatest() <= 2;
          } else if (unreadRow) {
            history.scrollTop += unreadRow.getBoundingClientRect().top -
              history.getBoundingClientRect().top;
          }
          if (unreadAnchor?.key === key) unreadAnchor = null;
          initialized = true;
          forced = false;
          appliedTop = history.scrollTop;
          position = !followBottom && row && saved?.anchor
            ? { ...saved, top: history.scrollTop, bottom: false }
            : readPosition() || position;
          setPositionedKey(name);
        } else if (forced || followBottom) {
          history.scrollTop = history.scrollHeight;
          followBottom = true;
          forced = false;
          appliedTop = history.scrollTop;
          position = readPosition() || position;
        } else {
          const row = findRow(position?.anchor?.id);
          if (row) {
            const delta = row.getBoundingClientRect().top -
              history.getBoundingClientRect().top - position.anchor.offset;
            if (Math.abs(delta) > 0.5) history.scrollTop += delta;
          } else {
            position = readPosition() || position;
          }
          appliedTop = history.scrollTop;
        }
        setShowLatest(distanceToLatest() > 24);
      };
      const scheduleLatest = (force = false) => {
        if (force) {
          forced = true;
          followBottom = true;
        }
        if (!frame) frame = window.requestAnimationFrame(apply);
      };
      const handleScroll = () => {
        if (!initialized || !current()) return;
        if (!forced && (appliedTop === null || Math.abs(history.scrollTop - appliedTop) > 1)) {
          followBottom = distanceToLatest() <= 24;
          position = readPosition() || position;
          appliedTop = history.scrollTop;
        }
        setShowLatest(distanceToLatest() > 24);
        if (!captureTimer) captureTimer = window.setTimeout(() => {
          captureTimer = 0;
          persist();
        }, 100);
      };
      // Every message can resize after an image loads or content-visibility
      // reveals it. Observe all rows, not just the last one.
      const resizeObserver = typeof ResizeObserver === "function"
        ? new ResizeObserver(() => scheduleLatest())
        : null;
      const observed = new Set();
      const observeRows = () => {
        const rows = new Set(history.children);
        for (const row of observed) {
          if (!rows.has(row)) {
            resizeObserver?.unobserve(row);
            observed.delete(row);
          }
        }
        for (const row of rows) {
          if (!observed.has(row)) {
            resizeObserver?.observe(row);
            observed.add(row);
          }
        }
      };
      const mutationObserver = typeof MutationObserver === "function"
        ? new MutationObserver(() => {
            observeRows();
            scheduleLatest();
          })
        : null;
      history.addEventListener("scroll", handleScroll, { passive: true });
      resizeObserver?.observe(history);
      mutationObserver?.observe(history, { childList: true });
      observeRows();
      capturePosition = capture;
      schedulePosition = scheduleLatest;
      requestLatestScroll = () => scheduleLatest(true);
      const onVisibilityChange = () => {
        if (document.hidden) capture();
      };
      document.addEventListener("visibilitychange", onVisibilityChange);
      window.addEventListener("pagehide", capture);
      scheduleLatest();
      return () => {
        if (frame) window.cancelAnimationFrame(frame);
        window.clearTimeout(captureTimer);
        capture();
        setPositionedKey("");
        setShowLatest(false);
        document.removeEventListener("visibilitychange", onVisibilityChange);
        window.removeEventListener("pagehide", capture);
        history.removeEventListener("scroll", handleScroll);
        resizeObserver?.disconnect();
        mutationObserver?.disconnect();
        capturePosition = () => {};
        schedulePosition = () => {};
        requestLatestScroll = () => {};
      };
    },
  );
  const openChat = async (chat, { restoring = false } = {}) => {
    const chatKey = (chat.type === "personal" ? "personal:" : "conversation:") + chat.id;
    saveViewPreference(viewAccountKey(options.profile), "chats.active", chatKey);
    const previousRequest = openingChatRequest;
    if (activeChatKey() === chatKey && (previousRequest?.key === chatKey ||
      !options.chatState.messagesLoading)) return;
    capturePosition();
    unreadAnchor = null;
    previousRequest?.controller.abort();
    olderRequest?.abort();
    setLoadingOlder(false);
    const previousKey = activeChatKey();
    if (previousKey && previousKey !== chatKey && !options.chatState.messagesLoading) {
      cache.saveHistory(previousKey, options.chatState.messages, olderCursor());
    }
    const role = options.profile?.role;
    const position = savedPosition(chatKey, restoring ? options.chatState.messageFilter : "all");
    const unreadCount = !position &&
      (role !== "admin" || chat.type === "personal") ? Number(chat.unread_count) || 0 : 0;
    const candidate = unreadCount ? null : cache.getHistory(chatKey);
    const cached = candidate && (!position?.anchor || position.bottom === true ||
      candidate.messages.some(item => "message:" + item.id === position.anchor.id)) ? candidate : null;
    const cachedMessages = cached?.messages || null;
    const controller = new AbortController();
    openingChatRequest = { key: chatKey, controller, hasCache: Boolean(cachedMessages) };
    // Блокируем запись старой истории под ключом нового чата на время
    // синхронного переключения сигналов.
    options.chatState.setMessagesLoading(true);
    setOlderCursor(cached?.olderCursor || 0);
    options.chatState.setSelectedChat(chat);
    options.chatState.setMessages(cachedMessages || []);
    options.chatState.setMessagesLoading(!cachedMessages);
    options.setPage("chats");
    options.chatState.setDraft("");
    options.chatState.setAttachment(null);
    if (!restoring) options.chatState.setMessageFilter("all");
    try {
      if (cached) {
        // A warm chat is rendered from its complete cached window. Reconcile
        // known IDs and append new messages without replacing its scroll geometry.
        let afterId = cachedMessages.reduce((max, row) => Math.max(max, Number(row.id) || 0), 0);
        let knownIds = cachedMessages.map(row => Number(row.id)).filter(id => Number.isSafeInteger(id) && id > 0);
        for (;;) {
          const result = await syncChatState(options.request, chat, afterId, knownIds, controller.signal);
          if (controller.signal.aborted || activeChatKey() !== chatKey) return;
          const deleted = new Set(result.deleted_message_ids.map(Number));
          for (const id of deleted) {
            markConversationMessageDeleted(chatKey, id);
            cache.removeMessage(chatKey, id);
          }
          options.chatState.setMessages(previous => mergeConversationMessages(
            previous.filter(row => !deleted.has(Number(row.id))),
            [...result.updated_messages, ...result.messages], chatKey));
          const next = result.messages.reduce((max, row) => Math.max(max, Number(row.id) || 0), afterId);
          if (!result.has_more || next <= afterId) break;
          afterId = next;
          knownIds = [];
        }
        openingChatRequest.windowReady = true;
        schedulePosition();
        return;
      }
      const anchor = position?.anchor?.id;
      const targetId = position?.bottom !== true && /^message:\d+$/.test(anchor || "") ? Number(anchor.slice(8)) : 0;
      let loadedMessages;
      let newerPage;
      let hasOlder;
      if (targetId || unreadCount) {
        const window = await getChatWindow(options.request, chat, controller.signal, targetId);
        loadedMessages = window.messages;
        hasOlder = window.has_older;
        newerPage = window.has_newer ? loadedMessages.slice(-HISTORY_PAGE_SIZE) : null;
        if (!targetId && window.anchor_id) unreadAnchor = { key: chatKey, id: window.anchor_id };
      } else {
        loadedMessages = await getChatMessages(options.request, chat, controller.signal);
        hasOlder = loadedMessages.length === HISTORY_PAGE_SIZE;
      }
      if (controller.signal.aborted || activeChatKey() !== chatKey) return;
      setOlderCursor(hasOlder ? loadedMessages[0].id : 0);
      // Сервер — источник истины: удалённые в другом окне сообщения не
      // остаются в кэше. Одновременно сохраняем изменения SSE за время запроса.
      options.chatState.setMessages((previous) => {
        return mergeConversationMessages(loadedMessages, previous, chatKey);
      });
      openingChatRequest.windowReady = true;
      schedulePosition();
      // The first screen is ready; append newer history without delaying it.
      while (newerPage?.length === HISTORY_PAGE_SIZE) {
        const after = Number(newerPage[newerPage.length - 1].id);
        newerPage = await getChatMessages(options.request, chat, controller.signal, null, after);
        if (controller.signal.aborted || activeChatKey() !== chatKey) return;
        if (!newerPage.length || Number(newerPage[0].id) <= after) break;
        options.chatState.setMessages(rows => mergeConversationMessages(newerPage, rows, chatKey));
      }
    } catch (error) {
      if (!controller.signal.aborted && activeChatKey() === chatKey) {
        openingChatRequest = null;
        if ([401, 403, 404].includes(error.status)) {
          cache.removeChat(chatKey);
          options.chatState.setSelectedChat(null);
          options.chatState.setMessages([]);
          options.chatState.setMessagesLoading(false);
        }
        options.setError(error.message);
      }
    } finally {
      if (!controller.signal.aborted && activeChatKey() === chatKey) {
        options.chatState.setMessagesLoading(false);
        schedulePosition();
      }
      if (openingChatRequest?.controller === controller) openingChatRequest = null;
    }
  };
  // Reopen the same conversation once its list has been loaded.
  createEffect(
    () => [
      viewAccountKey(options.profile),
      options.inboxLoading,
      options.chatState.chats,
      options.personalState.personalChats,
    ],
    ([userId, loading, conversations, personals]) => {
      if (userId == null || attemptedRestoreForUser === userId) return;
      const selected = options.chatState.selectedChat;
      if (selected) {
        attemptedRestoreForUser = userId;
        if (options.chatState.messagesLoading) void openChat(selected, { restoring: true });
        return;
      }
      const key = viewPreference(userId, "chats.active", "");
      if (!/^(conversation|personal):\d+$/.test(key)) return;
      const [type, idText] = key.split(":");
      const chat = (type === "personal" ? personals : conversations)
        .find(item => String(item.id) === idText);
      // Participant and personal inboxes arrive independently. Open as soon as
      // the selected conversation is available, even if the other list is slow.
      if (!chat && loading) return;
      attemptedRestoreForUser = userId;
      if (!chat) {
        saveViewPreference(userId, "chats.active", null);
        return;
      }
      if (type === "personal") options.personalState.setChatSection("personal");
      void openChat(chat, { restoring: true });
    },
  );
  const loadOlder = async () => {
    const chat = options.chatState.selectedChat;
    const key = activeChatKey();
    if (!chat || !olderCursor() || loadingOlder()) return;
    const controller = new AbortController();
    olderRequest = controller;
    setLoadingOlder(true);
    try {
      const page = await getChatMessages(options.request, chat, controller.signal, olderCursor());
      if (controller.signal.aborted || key !== activeChatKey()) return;
      capturePosition();
      options.chatState.setMessages(rows => mergeConversationMessages(page, rows, key));
      setOlderCursor(page.length >= HISTORY_PAGE_SIZE ? page[0].id : 0);
      schedulePosition();
    } catch (error) {
      if (!controller.signal.aborted && key === activeChatKey()) options.setError(error.message);
    } finally {
      if (controller === olderRequest) setLoadingOlder(false);
    }
  };
  const openCreatePersonalChat = () => {
    options.setModal({
      mode: "create-personal",
    });
  };
  const createPersonalChat = async (userId) => {
    if (creating()) return;
    setCreating(true);
    try {
      let chat = options.personalState.personalChats.find((item) => item.participant.id === userId);
      if (!chat) {
        chat = await createPersonalConversation(options.request, userId);
        options.personalState.setPersonalChats((current) =>
          current.some((item) => item.id === chat.id) ? current : [chat, ...current],
        );
      }
      options.setModal(null);
      await openChat(chat);
    } catch (error) {
      options.setError(error.message);
    } finally {
      setCreating(false);
    }
  };
  const confirmDeletePersonalChat = async () => {
    const chat = actions.deletePersonalChatCandidate;
    if (!chat || chat.type !== "personal" || options.profile?.role !== "admin" || actions.deletingPersonalChat) return;
    actions.setDeletingPersonalChat(true);
    const key = "personal:" + chat.id;
    try {
      const result = await deletePersonalConversation(options.request, chat.id);
      cache.removeChat(key);
      options.personalState.setPersonalChats((current) => current.filter((row) => row.id !== chat.id));
      if (viewPreference(viewAccountKey(options.profile), "chats.active", "") === key) {
        saveViewPreference(viewAccountKey(options.profile), "chats.active", null);
      }
      if (activeChatKey() === key) {
        openingChatRequest?.controller.abort();
        olderRequest?.abort();
        setOlderCursor(0);
        setLoadingOlder(false);
        options.chatState.setSelectedChat(null);
        options.chatState.setMessages([]);
        options.chatState.setMessagesLoading(false);
        options.chatState.setDraft("");
        options.chatState.setAttachment(null);
      }
      actions.setDeletePersonalChatCandidate(null);
      options.notify(result.media_cleanup_pending
        ? "Диалог удалён у всех. Очистка вложений продолжится автоматически."
        : "Личный диалог и все его сообщения и вложения удалены у всех участников");
    } catch (error) {
      options.setError(error.message || "Не удалось удалить личный диалог");
    } finally {
      actions.setDeletingPersonalChat(false);
    }
  };
  const confirmDeleteMessage = async () => {
    const message = actions.deleteMessageCandidate;
    if (!message || actions.deletingMessage) return;
    const chat = options.chatState.selectedChat;
    if (!chat) return;
    const chatKey = activeChatKey();
    actions.setDeletingMessage(true);
    try {
      const result = await deleteChatMessage(options.request, message, chat.type === "personal");
      markConversationMessageDeleted(chatKey, message.id);
      cache.removeMessage(chatKey, message.id);
      if (activeChatKey() === chatKey) {
        options.chatState.setMessages((current) => current.filter((item) => item.id !== message.id));
      }
      actions.setDeleteMessageCandidate(null);
      const messengerFailed = Number(result.messenger_failed ?? result.telegram_failed ?? 0);
      const messengerQueued = Number(result.messenger_delete_queued ?? 0);
      if (messengerQueued > 0) {
        options.notify("Сообщение удалено из UknowApp. Внешние копии поставлены в очередь удаления (" + messengerQueued + ")." + (messengerFailed ? " Неизвестных результатов отправки: " + messengerFailed + "." : ""));
      } else if (messengerFailed > 0) {
        options.notify(
          "Сообщение удалено из UknowApp. " +
            "Часть копий в мессенджерах удалить не удалось (" + messengerFailed + ").",
        );
      } else {
        options.notify("Сообщение удалено из UknowApp");
      }
    } catch (error) {
      options.setError(error.message || "Не удалось удалить сообщение");
    } finally {
      actions.setDeletingMessage(false);
    }
  };
  const sendChatMessage = async (event) => {
    event.preventDefault();
    const chat = options.chatState.selectedChat;
    const chatKey = chat ? (chat.type === "personal" ? "personal:" : "conversation:") + chat.id : "";
    const text = options.chatState.draft.trim();
    const file = options.chatState.attachment;
    if (!chat || (!text && !file) || sendingMessage) return;
    const limit = options.profile?.max_attachment_bytes;
    if (file && limit && file.size > limit) {
      options.setError("Максимальный размер вложения — " + limit / 1024 ** 2 + " МиБ");
      return;
    }
    sendingMessage = true;
    const optimistic = chat.type !== "personal" && !file && Boolean(text);
    const signature = [
      chat.type,
      chat.id,
      text,
      file?.name || "",
      file?.size || 0,
      file?.lastModified || 0,
    ].join(":");
    const pending = pendingClientMessage;
    const clientMessageId =
      (pending?.signature === signature ? pending.id : null) ||
      window.crypto?.randomUUID?.() ||
      Date.now().toString(36) + Math.random().toString(36).slice(2);
    pendingClientMessage = {
      signature,
      id: clientMessageId,
    };
    const optimisticId = clientMessageId ? "local-" + clientMessageId : null;
    if (optimistic) {
      options.chatState.setDraft("");
      options.chatState.setMessages((current) => [
        ...current,
        {
          id: optimisticId,
          sender: options.profile?.full_name || "",
          sender_role: options.profile?.role || "",
          can_delete: false,
          content_type: "text",
          text,
          metadata: {
            client_message_id: clientMessageId,
          },
          delivery_status: "pending",
          panel_read_at: null,
          created_at: new Date().toISOString(),
        },
      ]);
    }
    try {
      let sentMessage;
      if (chat.type === "personal") {
        sentMessage = file
          ? await sendConversationAttachment(chat.id, file, text, clientMessageId, true)
          : await sendPersonalMessage(options.request, chat.id, text, clientMessageId);
      } else if (file) {
        sentMessage = await sendConversationAttachment(chat.id, file, text, clientMessageId);
      } else {
        sentMessage = await sendConversationText(options.request, chat.id, text, clientMessageId);
      }
      pendingClientMessage = null;
      if (activeChatKey() !== chatKey) return;
      if (!optimistic) {
        options.chatState.setDraft("");
        options.chatState.setAttachment(null);
      }
      options.chatState.setMessages((current) => mergeConversationMessages(current, [sentMessage], chatKey));
      requestLatestScroll();
    } catch (error) {
      if (clientMessageId && activeChatKey() === chatKey) {
        options.chatState.setMessages((current) =>
          current.filter(
            (item) => item.id !== optimisticId && item.metadata?.client_message_id !== clientMessageId,
          ),
        );
        options.chatState.setDraft((current) => current || text);
      }
      options.setError(error.message);
    } finally {
      sendingMessage = false;
    }
  };
  return {
    get creating() {
      return creating();
    },
    get visibleChats() {
      return visibleChats();
    },
    get visibleMessages() {
      return visibleMessages();
    },
    capturePosition: () => capturePosition(),
    get showLatest() { return showLatest(); },
    scrollToLatest: () => requestLatestScroll(),
    get positionReady() { return positionedKey() === positionName(activeChatKey(), options.chatState.messageFilter); },
    get hasOlder() { return olderCursor() > 0; },
    get loadingOlder() { return loadingOlder(); },
    loadOlder,
    openChat,
    openCreatePersonalChat,
    createPersonalChat,
    confirmDeleteMessage,
    confirmDeletePersonalChat,
    sendChatMessage,
    get deleteMessageCandidate() {
      return actions.deleteMessageCandidate;
    },
    get deletingMessage() {
      return actions.deletingMessage;
    },
    setDeleteMessageCandidate: actions.setDeleteMessageCandidate,
    get deletePersonalChatCandidate() {
      return actions.deletePersonalChatCandidate;
    },
    get deletingPersonalChat() {
      return actions.deletingPersonalChat;
    },
    setDeletePersonalChatCandidate: actions.setDeletePersonalChatCandidate,
  };
}
