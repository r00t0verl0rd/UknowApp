import { useCallback, useEffect, useLayoutEffect, useMemo } from "react";
import { useChatActionState } from "./useChatActionState.js";
import { useConversationSync } from "./useConversationSync.js";
import {
  createPersonalConversation, deleteChatMessage, getChatMessages,
  sendConversationAttachment,
  sendConversationText, sendPersonalMessage,
} from "../services/conversationsApi.js";

export function useChatsController({
  auth, page, request, profile, chatState, personalState, setPage, setError, setModal,
  notify,
}) {
  const { deleteMessageCandidate, deletingMessage, setDeletingMessage, setDeleteMessageCandidate } = useChatActionState();
  const {
    chats, setChats, selectedChat, setSelectedChat, messages, setMessages,
    draft, setDraft, attachment, setAttachment, messagesViewportRef,
    chatSearch, chatFilter, messageFilter, setMessageFilter,
  } = chatState;
  const { personalChats, setPersonalChats, chatSection, setChatSection } = personalState;

  useConversationSync({ auth, page, role: profile?.role, selectedChat, messages, request, setChats, setPersonalChats, setMessages });

  useEffect(() => {
    if (!auth || !profile) return;
    const params = new URLSearchParams(window.location.search);
    const conversationId = Number(params.get("openConversation"));
    if (!conversationId) return;
    const personal = params.get("type") === "personal";
    const source = personal ? personalChats : chats;
    const chat = source.find(item => Number(item.id) === conversationId);
    if (!chat) return;
    window.history.replaceState({}, "", window.location.pathname + window.location.hash);
    setPage("chats");
    if (personal) setChatSection("personal");
    setSelectedChat(chat);
    setMessages([]);
    void getChatMessages(request, chat)
      .then(setMessages)
      .catch(error => setError(error.message));
  }, [auth, profile, personalChats, chats, request, setPage, setChatSection, setSelectedChat, setMessages, setError]);

  const visibleMessages = useMemo(() => {
    if (messageFilter === "all") return messages;
    return messages.filter(message => {
      const kind = message.metadata?.media?.kind || message.content_type;
      if (messageFilter === "media") return kind !== "text" || Boolean(message.metadata?.media);
      if (messageFilter === "audio") return ["voice", "audio"].includes(kind);
      if (messageFilter === "photos") return kind === "photo";
      if (messageFilter === "files") return ["document", "video", "video_note", "video_sticker", "animation", "animated_sticker", "sticker"].includes(kind);
      return true;
    });
  }, [messages, messageFilter]);

  const visibleChats = useMemo(() => {
    const query = chatSearch.trim().toLocaleLowerCase("ru");
    const personal = personalChats.filter(chat =>
      (!query || chat.title.toLocaleLowerCase("ru").includes(query))
      && (chatFilter === "all" || Number(chat.unread_count || 0) > 0));
    if (profile?.role === "admin" && chatSection === "personal") return personal;
    const regular = profile?.role === "student" ? chats.slice(0, 1) : chats.filter(chat => {
      const names = profile?.role === "admin"
        ? chat.teacher.full_name + " " + chat.student.full_name
        : chat.student.full_name + " " + chat.teacher.full_name;
      const matchesSearch = !query || names.toLocaleLowerCase("ru").includes(query);
      const matchesFilter = profile?.role !== "teacher" || chatFilter === "all" || Number(chat.unread_count || 0) > 0;
      return matchesSearch && matchesFilter;
    });
    return profile?.role === "admin" ? regular : [...regular, ...personal];
  }, [chats, personalChats, chatSection, chatSearch, chatFilter, profile?.role]);

  useLayoutEffect(() => {
    const viewport = messagesViewportRef.current;
    if (!viewport) return undefined;
    let stickToBottom = true;
    const scrollToLatest = () => {
      if (stickToBottom) viewport.scrollTop = viewport.scrollHeight;
    };
    const handleScroll = () => {
      stickToBottom = viewport.scrollHeight - viewport.scrollTop - viewport.clientHeight < 80;
    };
    viewport.addEventListener("scroll", handleScroll, { passive: true });
    scrollToLatest();
    const frame = window.requestAnimationFrame(scrollToLatest);
    const resizeObserver = typeof ResizeObserver !== "undefined"
      ? new ResizeObserver(scrollToLatest)
      : null;
    const observeMessages = () => {
      if (resizeObserver) Array.from(viewport.children).forEach(child => resizeObserver.observe(child));
    };
    observeMessages();
    const mutationObserver = typeof MutationObserver !== "undefined"
      ? new MutationObserver(() => { observeMessages(); scrollToLatest(); })
      : null;
    mutationObserver?.observe(viewport, { childList: true, subtree: true });
    return () => {
      window.cancelAnimationFrame(frame);
      viewport.removeEventListener("scroll", handleScroll);
      resizeObserver?.disconnect();
      mutationObserver?.disconnect();
    };
  }, [selectedChat?.id, selectedChat?.type, messageFilter, messagesViewportRef]);

  const openChat = useCallback(async chat => {
    setSelectedChat(chat);
    setMessages([]);
    setPage("chats");
    setDraft("");
    setAttachment(null);
    setMessageFilter("all");
    try {
      setMessages(await getChatMessages(request, chat));
    } catch (error) {
      setError(error.message);
    }
  }, [setSelectedChat, setPage, setDraft, setAttachment, setMessageFilter, setMessages, request, setError]);

  const openCreatePersonalChat = useCallback(() => {
    setError("");
    setModal({ mode: "create-personal" });
  }, [setError, setModal]);

  const createPersonalChat = useCallback(async userId => {
    try {
      const chat = await createPersonalConversation(request, userId);
      setPersonalChats(current => current.some(item => item.id === chat.id)
        ? current.map(item => item.id === chat.id ? { ...item, ...chat } : item)
        : [...current, chat]);
      setChatSection("personal");
      setModal(null);
      await openChat(chat);
    } catch (error) {
      setError(error.message);
    }
  }, [request, setPersonalChats, setChatSection, setModal, openChat, setError]);

  const confirmDeleteMessage = useCallback(async () => {
    const message = deleteMessageCandidate;
    if (!message || deletingMessage) return;
    setDeletingMessage(true);
    setError("");
    try {
      const result = await deleteChatMessage(request, message, selectedChat?.type === "personal");
      setMessages(current => current.filter(item => item.id !== message.id));
      setDeleteMessageCandidate(null);
      const messengerFailed = Number(result.messenger_failed ?? result.telegram_failed ?? 0);
      if (messengerFailed > 0) {
        notify("Сообщение удалено из UknowApp. Не удалось удалить копии во внешних мессенджерах: " + messengerFailed + ".");
      } else {
        notify("Сообщение удалено у всех участников");
      }
    } catch (error) {
      setError(error.message || "Не удалось удалить сообщение");
    } finally {
      setDeletingMessage(false);
    }
  }, [deleteMessageCandidate, deletingMessage, setDeletingMessage, setError, request, selectedChat, setMessages, setDeleteMessageCandidate, notify]);

  const sendChatMessage = useCallback(async event => {
    event.preventDefault();
    const chat = selectedChat;
    const text = draft.trim();
    const file = attachment;
    if (!chat || (!text && !file)) return;

    const optimistic = chat.type !== "personal" && !file && Boolean(text);
    const clientMessageId = optimistic
      ? (window.crypto?.randomUUID?.() || Date.now().toString(36) + Math.random().toString(36).slice(2))
      : null;
    const optimisticId = clientMessageId ? "local-" + clientMessageId : null;

    if (optimistic) {
      setDraft("");
      setMessages(current => [...current, {
        id: optimisticId,
        sender: profile?.full_name || "",
        sender_role: profile?.role || "",
        can_delete: false,
        content_type: "text",
        text,
        metadata: { client_message_id: clientMessageId },
        delivery_status: "pending",
        panel_read_at: null,
        created_at: new Date().toISOString(),
      }]);
    }

    try {
      let sentMessage;
      if (chat.type === "personal") {
        if (file) throw new Error("В личных диалогах доступны только текстовые сообщения");
        sentMessage = await sendPersonalMessage(request, chat.id, text);
      } else if (file) {
        sentMessage = await sendConversationAttachment(chat.id, file, text);
      } else {
        sentMessage = await sendConversationText(request, chat.id, text, clientMessageId);
      }

      if (!optimistic) {
        setDraft("");
        setAttachment(null);
      }
      setMessages(current => {
        const reconciled = clientMessageId
          ? current.filter(item => item.id !== optimisticId && item.metadata?.client_message_id !== clientMessageId)
          : current;
        const existing = reconciled.findIndex(item => item.id === sentMessage.id);
        if (existing >= 0) {
          return reconciled.map(item => item.id === sentMessage.id ? sentMessage : item);
        }
        return [...reconciled, sentMessage];
      });

      if (chat.type === "personal") notify("Сообщение отправлено внутри UknowApp");
      else if (profile?.role === "admin" && sentMessage?.delivery_status !== "delivered") {
        notify("Сообщение сохранено. Подробности доставки доступны в переписке.");
      } else if (sentMessage?.delivery_status === "delivered" && profile?.role !== "teacher") {
        notify("Сообщение отправлено");
      }
    } catch (error) {
      if (clientMessageId) {
        setMessages(current => current.filter(item =>
          item.id !== optimisticId && item.metadata?.client_message_id !== clientMessageId
        ));
        setDraft(current => current || text);
      }
      setError(error.message);
    }
  }, [selectedChat, draft, attachment, request, setDraft, setMessages, setAttachment, notify, profile?.role, profile?.full_name, setError]);

  return { visibleChats, visibleMessages, openChat, openCreatePersonalChat, createPersonalChat, confirmDeleteMessage, sendChatMessage, deleteMessageCandidate, deletingMessage, setDeleteMessageCandidate };
}
