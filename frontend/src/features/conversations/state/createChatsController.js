import { createSignal, createMemo, createEffect } from "solid-js";
import { createChatActionState } from "./createChatActionState.js";
import { readScrollPositions, saveViewPreference, viewPreference } from "../../../shared/services/viewSession.js";
import { markConversationMessageDeleted, mergeConversationMessages } from "../services/messageState.js";
import {
  createPersonalConversation,
  deleteChatMessage,
  deletePersonalConversation,
  getChatMessages,
  HISTORY_PAGE_SIZE,
  sendConversationAttachment,
  sendConversationText,
  sendPersonalMessage,
} from "../services/conversationsApi.js";
export function createChatsController(options) {
  const actions = createChatActionState();
  const [creating, setCreating] = createSignal(false);
  const [olderCursor, setOlderCursor] = createSignal(0);
  const [loadingOlder, setLoadingOlder] = createSignal(false);
  let olderRequest;
  let sendingMessage = false;
  let pendingClientMessage = null;
  let openingChatRequest = null;
  let attemptedRestoreForUser = null;
  let restoredChatScrollKey = "";
  // Только память текущей вкладки. Недавние чаты показываем сразу, затем
  // проверяем сервер; не сохраняем приватные сообщения в localStorage.
  const recentChats = new Map();
  const MAX_CACHED_CHATS = 6;
  const CACHE_TTL_MS = 60000;
  const cacheChat = (key, messages) => {
    if (!key || !messages?.length || messages.length > 1200) return;
    recentChats.delete(key);
    recentChats.set(key, { messages, at: Date.now() });
    while (recentChats.size > MAX_CACHED_CHATS) recentChats.delete(recentChats.keys().next().value);
  };
  const getCachedChat = (key) => {
    const cache = recentChats.get(key);
    if (!cache) return null;
    if (Date.now() - cache.at > CACHE_TTL_MS) {
      recentChats.delete(key);
      return null;
    }
    return cache.messages;
  };
  createEffect(
    () => [options.auth],
    () => {
      if (!options.auth) recentChats.clear();
    },
  );
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
    () => [activeChatKey(), options.chatState.messages, options.chatState.messagesLoading],
    ([key, messages, loading]) => {
      if (key && !loading && Array.isArray(messages)) cacheChat(key, messages);
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
  let requestLatestScroll = () => {};
  const preservingScroll = key => key && restoredChatScrollKey === key &&
    Object.hasOwn(readScrollPositions(options.profile?.id, "chats"), `messages:${key}`);
  createEffect(
    () => [
      options.chatState.selectedChat?.id,
      options.chatState.selectedChat?.type,
      options.chatState.messageFilter,
    ],
    () => {
      const history = options.chatState.messagesViewportRef.current;
      if (!history) return undefined;
      let frame = 0;
      let followBottom = !preservingScroll(activeChatKey());
      let forced = false;
      let lastObserved = null;
      const distanceToLatest = () =>
        history.scrollHeight - history.scrollTop - history.clientHeight;
      const scrollToLatest = () => {
        frame = 0;
        if (forced || followBottom) {
          history.scrollTop = history.scrollHeight;
          followBottom = true;
        }
        forced = false;
      };
      const scheduleLatest = (force = false) => {
        if (force) {
          forced = true;
          followBottom = true;
        }
        if (!frame) frame = window.requestAnimationFrame(scrollToLatest);
      };
      const handleScroll = () => {
        if (!forced) followBottom = distanceToLatest() < 80;
      };
      const resizeObserver = typeof ResizeObserver === "function"
        ? new ResizeObserver(() => scheduleLatest())
        : null;
      const observeLastMessage = () => {
        const latest = history.lastElementChild;
        if (latest === lastObserved) return;
        if (lastObserved) resizeObserver?.unobserve(lastObserved);
        lastObserved = latest;
        if (latest) resizeObserver?.observe(latest);
      };
      const mutationObserver = typeof MutationObserver === "function"
        ? new MutationObserver(() => {
            observeLastMessage();
            scheduleLatest();
          })
        : null;
      history.addEventListener("scroll", handleScroll, { passive: true });
      resizeObserver?.observe(history);
      mutationObserver?.observe(history, { childList: true });
      observeLastMessage();
      requestLatestScroll = () => scheduleLatest(true);
      if (!preservingScroll(activeChatKey())) scheduleLatest(true);
      return () => {
        if (frame) window.cancelAnimationFrame(frame);
        history.removeEventListener("scroll", handleScroll);
        resizeObserver?.disconnect();
        mutationObserver?.disconnect();
        if (requestLatestScroll) requestLatestScroll = () => {};
      };
    },
  );
  let previousScrollChat = "";
  let previousTail = "";
  createEffect(
    () => [activeChatKey(), options.chatState.messageFilter, visibleMessages().at(-1)?.id],
    ([chatKey, , lastId]) => {
      const tail = lastId == null ? "" : String(lastId);
      if (chatKey !== previousScrollChat) {
        previousScrollChat = chatKey;
        previousTail = tail;
        if (chatKey && !preservingScroll(chatKey)) requestLatestScroll();
      } else if (tail && tail !== previousTail) {
        previousTail = tail;
        // Новое полученное или отправленное сообщение: показать его сразу.
        // Изменение статуса прочтения не вызывает повторную прокрутку.
        if (!preservingScroll(chatKey)) requestLatestScroll();
      } else if (!tail) {
        previousTail = "";
      }
    },
  );
  const openChat = async (chat, { restoring = false } = {}) => {
    const chatKey = (chat.type === "personal" ? "personal:" : "conversation:") + chat.id;
    restoredChatScrollKey = restoring ? chatKey : "";
    saveViewPreference(options.profile?.id, "chats.active", chatKey);
    const previousRequest = openingChatRequest;
    if (activeChatKey() === chatKey && (previousRequest?.key === chatKey ||
      !options.chatState.messagesLoading)) return;
    previousRequest?.controller.abort();
    olderRequest?.abort();
    setOlderCursor(0);
    setLoadingOlder(false);
    const previousKey = activeChatKey();
    if (previousKey && previousKey !== chatKey && !options.chatState.messagesLoading) {
      cacheChat(previousKey, options.chatState.messages);
    }
    const cachedMessages = getCachedChat(chatKey);
    const cachedById = new Map((cachedMessages || []).map((item) => [String(item.id), item]));
    const controller = new AbortController();
    openingChatRequest = { key: chatKey, controller };
    // Блокируем запись старой истории под ключом нового чата на время
    // синхронного переключения сигналов.
    options.chatState.setMessagesLoading(true);
    options.chatState.setSelectedChat(chat);
    options.chatState.setMessages(cachedMessages || []);
    options.chatState.setMessagesLoading(!cachedMessages);
    options.setPage("chats");
    options.chatState.setDraft("");
    options.chatState.setAttachment(null);
    if (!restoring) options.chatState.setMessageFilter("all");
    try {
      let loadedMessages = await getChatMessages(options.request, chat, controller.signal);
      if (controller.signal.aborted || activeChatKey() !== chatKey) return;
      // A view restored in the middle of a long conversation can be older than
      // the last 50 messages. Load preceding pages only for that specific chat.
      const anchor = restoring
        ? readScrollPositions(options.profile?.id, "chats")[`messages:${chatKey}`]?.anchor?.id
        : null;
      const targetId = /^message:\d+$/.test(anchor || "") ? Number(anchor.slice(8)) : 0;
      if (targetId && loadedMessages.length) {
        let pages = 0;
        while (loadedMessages.length >= HISTORY_PAGE_SIZE &&
          Number(loadedMessages[0].id) > targetId && pages < 16) {
          const previousOldest = Number(loadedMessages[0].id);
          const older = await getChatMessages(options.request, chat, controller.signal, previousOldest);
          if (controller.signal.aborted || activeChatKey() !== chatKey) return;
          if (!older.length || Number(older[0].id) >= previousOldest) break;
          loadedMessages = mergeConversationMessages(older, loadedMessages, chatKey);
          pages++;
          if (older.length < HISTORY_PAGE_SIZE) break;
        }
      }
      setOlderCursor(loadedMessages.length >= HISTORY_PAGE_SIZE ? loadedMessages[0].id : 0);
      // Сервер — источник истины: удалённые в другом окне сообщения не
      // остаются в кэше. Одновременно сохраняем изменения SSE за время запроса.
      options.chatState.setMessages((previous) => {
        const receivedDuringLoad = cachedMessages
          ? previous.filter((item) => cachedById.get(String(item.id)) !== item)
          : previous;
        const merged = mergeConversationMessages(loadedMessages, receivedDuringLoad, chatKey);
        cacheChat(chatKey, merged);
        return merged;
      });
    } catch (error) {
      if (!controller.signal.aborted && activeChatKey() === chatKey) {
        openingChatRequest = null;
        options.setError(error.message);
      }
    } finally {
      if (!controller.signal.aborted && activeChatKey() === chatKey) {
        options.chatState.setMessagesLoading(false);
      }
      if (openingChatRequest?.controller === controller) openingChatRequest = null;
    }
  };
  // Reopen the same conversation once its list has been loaded.
  createEffect(
    () => [
      options.profile?.id,
      options.inboxLoading,
      options.chatState.chats,
      options.personalState.personalChats,
    ],
    ([userId, loading, conversations, personals]) => {
      if (userId == null || loading || attemptedRestoreForUser === userId) return;
      attemptedRestoreForUser = userId;
      const selected = options.chatState.selectedChat;
      if (selected) {
        if (options.chatState.messagesLoading) void openChat(selected, { restoring: true });
        return;
      }
      const key = viewPreference(userId, "chats.active", "");
      if (!/^(conversation|personal):\d+$/.test(key)) return;
      const [type, idText] = key.split(":");
      const chat = (type === "personal" ? personals : conversations)
        .find(item => String(item.id) === idText);
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
      const viewport = options.chatState.messagesViewportRef.current;
      const height = viewport?.scrollHeight;
      const scrollTop = viewport?.scrollTop;
      options.chatState.setMessages(rows => mergeConversationMessages(page, rows, key));
      setOlderCursor(page.length >= HISTORY_PAGE_SIZE ? page[0].id : 0);
      requestAnimationFrame(() => {
        if (viewport && key === activeChatKey()) viewport.scrollTop = scrollTop + viewport.scrollHeight - height;
      });
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
      await deletePersonalConversation(options.request, chat.id);
      recentChats.delete(key);
      options.personalState.setPersonalChats((current) => current.filter((row) => row.id !== chat.id));
      if (viewPreference(options.profile?.id, "chats.active", "") === key) {
        saveViewPreference(options.profile?.id, "chats.active", null);
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
      options.notify("Личный диалог и все его сообщения и вложения удалены у всех участников");
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
      if (activeChatKey() === chatKey) {
        options.chatState.setMessages((current) => current.filter((item) => item.id !== message.id));
      }
      actions.setDeleteMessageCandidate(null);
      const messengerFailed = Number(result.messenger_failed ?? result.telegram_failed ?? 0);
      if (messengerFailed > 0) {
        options.notify(
          "Сообщение удалено из UknowApp. " +
            "Часть копий в мессенджерах удалить не удалось (" + messengerFailed + ").",
        );
      } else {
        options.notify("Сообщение удалено из UknowApp и подключённых мессенджеров");
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
