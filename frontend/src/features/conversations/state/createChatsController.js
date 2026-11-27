import { createSignal, createMemo, createEffect } from "solid-js";
import { createChatActionState } from "./createChatActionState.js";
import { createMessageViewport } from "./createMessageViewport.js";
import { viewAccountKey, saveViewPreference, viewPreference } from "../../../shared/services/viewSession.js";
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
  const viewport = createMessageViewport(options, activeChatKey, () => openingChatRequest);
  const openChat = async (chat, { restoring = false } = {}) => {
    const chatKey = (chat.type === "personal" ? "personal:" : "conversation:") + chat.id;
    saveViewPreference(viewAccountKey(options.profile), "chats.active", chatKey);
    const previousRequest = openingChatRequest;
    if (activeChatKey() === chatKey && (previousRequest?.key === chatKey ||
      !options.chatState.messagesLoading)) return;
    viewport.capture();
    viewport.setUnreadAnchor(null);
    previousRequest?.controller.abort();
    olderRequest?.abort();
    setLoadingOlder(false);
    const previousKey = activeChatKey();
    if (previousKey && previousKey !== chatKey && !options.chatState.messagesLoading) {
      cache.saveHistory(previousKey, options.chatState.messages, olderCursor());
    }
    const role = options.profile?.role;
    const position = viewport.savedPosition(chatKey, restoring ? options.chatState.messageFilter : "all");
    const unreadCount = !position ? Number(role === "admin" && chat.type !== "personal"
      ? chat.admin_unread_count : chat.unread_count) || 0 : 0;
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
    options.chatState.setAttachments([]);
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
        viewport.schedule();
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
        if (!targetId && window.anchor_id) viewport.setUnreadAnchor({ key: chatKey, id: window.anchor_id });
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
      viewport.schedule();
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
        viewport.schedule();
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
      viewport.capture();
      options.chatState.setMessages(rows => mergeConversationMessages(page, rows, key));
      setOlderCursor(page.length >= HISTORY_PAGE_SIZE ? page[0].id : 0);
      viewport.schedule();
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
        options.chatState.setAttachments([]);
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
  const sendAttachments = async (chat, chatKey, text, entries) => {
    const senderAccount = viewAccountKey(options.profile);
    options.chatState.setSendingAttachments(true);
    let caption = text;
    let sent = 0;
    try {
      for (const entry of entries) {
        if (!options.auth || viewAccountKey(options.profile) !== senderAccount) break;
        try {
          const message = await sendConversationAttachment(
            chat.id, entry.file, caption, entry.id, chat.type === "personal",
          );
          sent++;
          if (!options.auth || viewAccountKey(options.profile) !== senderAccount) break;
          if (activeChatKey() === chatKey) {
            options.chatState.setMessages(current => mergeConversationMessages(current, [message], chatKey));
            // Do not touch a new draft after navigating away and reopening.
            if (options.chatState.attachments.some(item => item.id === entry.id)) {
              options.chatState.setAttachments(current => current.filter(item => item.id !== entry.id));
              if (caption) options.chatState.setDraft(current => current.trim() === caption ? "" : current);
            }
            viewport.scrollToLatest();
          }
          caption = "";
        } catch (error) {
          options.setError(`Не удалось отправить «${entry.file.name}»: ${error.message || "Ошибка запроса"}. Отправлено ${sent} из ${entries.length}.`);
          break;
        }
      }
    } finally {
      options.chatState.setSendingAttachments(false);
    }
  };
  const sendChatMessage = async (event) => {
    event.preventDefault();
    const chat = options.chatState.selectedChat;
    const chatKey = chat ? (chat.type === "personal" ? "personal:" : "conversation:") + chat.id : "";
    const text = options.chatState.draft.trim();
    const entries = options.chatState.attachments;
    if (!chat || (!text && !entries.length) || sendingMessage || options.chatState.sendingAttachments) return;
    if (entries.length) {
      if ([...text].length > 3900) {
        options.setError("Текст к вложению слишком длинный (максимум 3900 символов)");
        return;
      }
      const limit = options.profile?.max_attachment_bytes;
      const oversized = limit && entries.find(entry => entry.file.size > limit);
      if (oversized) {
        options.setError("«" + oversized.file.name + "»: максимальный размер вложения — " + limit / 1024 ** 2 + " МиБ");
        return;
      }
      await sendAttachments(chat, chatKey, text, entries);
      return;
    }
    sendingMessage = true;
    const optimistic = chat.type !== "personal" && Boolean(text);
    const senderRole = options.profile?.role;
    const signature = [
      chat.type,
      chat.id,
      text,
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
          sender_role: senderRole || "",
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
        sentMessage = await sendPersonalMessage(options.request, chat.id, text, clientMessageId);
      } else {
        sentMessage = await sendConversationText(options.request, chat.id, text, clientMessageId);
      }
      pendingClientMessage = null;
      if (activeChatKey() !== chatKey) return;
      if (!optimistic) options.chatState.setDraft(current => current.trim() === text ? "" : current);
      options.chatState.setMessages((current) => mergeConversationMessages(current, [sentMessage], chatKey));
      viewport.scrollToLatest();
    } catch (error) {
      if (clientMessageId && activeChatKey() === chatKey) {
        // A live update may confirm the send before its HTTP response is lost.
        if (optimistic && options.chatState.messages.some(item =>
          Number(item.id) > 0 && item.sender_role === senderRole &&
          item.metadata?.client_message_id === clientMessageId
        )) {
          pendingClientMessage = null;
          return;
        }
        options.chatState.setMessages(current => current.filter(item => item.id !== optimisticId));
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
    capturePosition: () => viewport.capture(),
    get showLatest() { return viewport.showLatest; },
    scrollToLatest: () => viewport.scrollToLatest(),
    get positionReady() { return viewport.positionReady; },
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
