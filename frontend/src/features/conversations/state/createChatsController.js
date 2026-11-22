import { createSignal, createMemo, createEffect } from "solid-js";
import { createChatActionState } from "./createChatActionState.js";
import { markConversationMessageDeleted, mergeConversationMessages } from "../services/messageState.js";
import {
  createPersonalConversation,
  deleteChatMessage,
  getChatMessages,
  sendConversationAttachment,
  sendConversationText,
  sendPersonalMessage,
} from "../services/conversationsApi.js";
export function createChatsController(options) {
  const actions = createChatActionState();
  const [creating, setCreating] = createSignal(false);
  let sendingMessage = false;
  let pendingClientMessage = null;
  let openingChatRequest = null;
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
  createEffect(
    () => [
      options.chatState.selectedChat?.id,
      options.chatState.selectedChat?.type,
      options.chatState.messageFilter,
      options.chatState.messagesViewportRef,
    ],
    () => {
      const history = options.chatState.messagesViewportRef.current;
      const viewport = history?.closest(".workspace-content");
      const detail = history?.closest(".chat-detail");
      if (!viewport || !detail) return undefined;
      const distanceToLatest = () => {
        const bottom = viewport.getBoundingClientRect().top + viewport.clientHeight;
        return detail.getBoundingClientRect().bottom - bottom;
      };
      let stickToBottom = true;
      const scrollToLatest = () => {
        if (stickToBottom) viewport.scrollTop += distanceToLatest();
      };
      const handleScroll = () => {
        stickToBottom = distanceToLatest() < 80;
      };
      viewport.addEventListener("scroll", handleScroll, {
        passive: true,
      });
      scrollToLatest();
      const frame = window.requestAnimationFrame(scrollToLatest);
      const resizeObserver =
        typeof ResizeObserver !== "undefined" ? new ResizeObserver(scrollToLatest) : null;
      resizeObserver?.observe(detail);
      resizeObserver?.observe(viewport);
      return () => {
        window.cancelAnimationFrame(frame);
        viewport.removeEventListener("scroll", handleScroll);
        resizeObserver?.disconnect();
      };
    },
  );
  const openChat = async (chat) => {
    const chatKey = (chat.type === "personal" ? "personal:" : "conversation:") + chat.id;
    const previousRequest = openingChatRequest;
    if (activeChatKey() === chatKey && previousRequest?.key === chatKey) return;
    previousRequest?.controller.abort();
    const controller = new AbortController();
    openingChatRequest = {
      key: chatKey,
      controller,
    };
    options.chatState.setSelectedChat(chat);
    options.chatState.setMessages([]);
    options.chatState.setMessagesLoading(true);
    options.setPage("chats");
    options.chatState.setDraft("");
    options.chatState.setAttachment(null);
    options.chatState.setMessageFilter("all");
    try {
      const loadedMessages = await getChatMessages(options.request, chat, controller.signal);
      if (controller.signal.aborted || activeChatKey() !== chatKey) return;
      // При загрузке истории сохраняем обновления из SSE.
      options.chatState.setMessages((previous) =>
        mergeConversationMessages(previous, loadedMessages, chatKey),
      );
    } catch (error) {
      if (!controller.signal.aborted && activeChatKey() === chatKey) {
        openingChatRequest = null;
        options.setError(error.message);
      }
    } finally {
      if (!controller.signal.aborted && activeChatKey() === chatKey) {
        options.chatState.setMessagesLoading(false);
      }
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
        options.setError(
          "Сообщение удалено из UknowApp. Не удалось удалить копии во внешних мессенджерах: " +
            messengerFailed +
            ".",
        );
      } else {
        options.notify("Сообщение удалено у всех участников");
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
        if (file) throw new Error("В личных диалогах доступны только текстовые сообщения");
        sentMessage = await sendPersonalMessage(options.request, chat.id, text, clientMessageId);
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
      if (chat.type !== "personal" && options.profile?.role === "admin") {
        const hasMessengerIssues = Object.values(sentMessage?.metadata?.messenger_deliveries || {}).some(
          (delivery) => (delivery?.errors || []).length > 0,
        );
        if (hasMessengerIssues)
          options.setError(
            "Сообщение доставлено в UknowApp. Подробности внешней доставки доступны в переписке.",
          );
      }
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
    openChat,
    openCreatePersonalChat,
    createPersonalChat,
    confirmDeleteMessage,
    sendChatMessage,
    get deleteMessageCandidate() {
      return actions.deleteMessageCandidate;
    },
    get deletingMessage() {
      return actions.deletingMessage;
    },
    setDeleteMessageCandidate: actions.setDeleteMessageCandidate,
  };
}
