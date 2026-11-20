import { useCallback, useLayoutEffect, useMemo } from "react";
import {
  createPersonalConversation, deleteChatMessage, getChatMessages,
  getConversations, getPersonalConversations, sendConversationAttachment,
  sendConversationText, sendPersonalMessage,
} from "../../modules/conversations/services/conversationsApi.js";

export function useChatsController({
  request, profile, chatState, personalState, setPage, setError, setModal,
  notify, deleteMessageCandidate, deletingMessage, setDeletingMessage,
  setDeleteMessageCandidate,
}) {
  const {
    chats, setChats, selectedChat, setSelectedChat, messages, setMessages,
    draft, setDraft, attachment, setAttachment, messagesViewportRef,
    chatSearch, chatFilter, messageFilter,
  } = chatState;
  const { personalChats, setPersonalChats, chatSection, setChatSection } = personalState;

  const visibleMessages = useMemo(() => messages.filter(message => {
    const kind = message.metadata?.media?.kind || message.content_type;
    if (messageFilter === "all") return true;
    if (messageFilter === "media") return kind !== "text" || Boolean(message.metadata?.media);
    if (messageFilter === "audio") return ["voice", "audio"].includes(kind);
    if (messageFilter === "photos") return kind === "photo";
    if (messageFilter === "files") return ["document", "video", "video_note", "video_sticker", "animation", "animated_sticker", "sticker"].includes(kind);
    return true;
  }), [messages, messageFilter]);

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
    const scrollToLatest = () => { viewport.scrollTop = viewport.scrollHeight; };
    scrollToLatest();
    const frame = window.requestAnimationFrame(scrollToLatest);
    const resizeObserver = typeof ResizeObserver !== "undefined" ? new ResizeObserver(scrollToLatest) : null;
    const observeMessages = () => {
      if (resizeObserver) Array.from(viewport.children).forEach(child => resizeObserver.observe(child));
    };
    observeMessages();
    const mutationObserver = typeof MutationObserver !== "undefined"
      ? new MutationObserver(() => { observeMessages(); scrollToLatest(); })
      : null;
    mutationObserver?.observe(viewport, { childList: true });
    return () => {
      window.cancelAnimationFrame(frame);
      resizeObserver?.disconnect();
      mutationObserver?.disconnect();
    };
  }, [selectedChat?.id, messageFilter, visibleMessages, messagesViewportRef]);

  const openChat = useCallback(async chat => {
    setSelectedChat(chat);
    setPage("chats");
    setDraft("");
    setAttachment(null);
    chatState.setMessageFilter("all");
    try {
      setMessages(await getChatMessages(request, chat));
      if (chat.type === "personal") setPersonalChats(await getPersonalConversations(request));
      else if (profile?.role === "teacher") setChats(await getConversations(request));
    } catch (error) {
      setError(error.message);
    }
  }, [setSelectedChat, setPage, setDraft, setAttachment, chatState, setMessages, request, setPersonalChats, profile?.role, setChats, setError]);

  const createPersonalChat = useCallback(async userId => {
    try {
      const chat = await createPersonalConversation(request, userId);
      setPersonalChats(await getPersonalConversations(request));
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
      if (selectedChat?.type === "personal") setPersonalChats(await getPersonalConversations(request));
      else if (selectedChat) setChats(await getConversations(request));
      if (result.telegram_failed > 0) {
        notify("Удалено из UknowApp. Не удалось удалить копии в Telegram: " + result.telegram_failed + ". Возможно, Telegram уже не разрешает их удаление.");
      } else {
        notify("Сообщение удалено у всех участников");
      }
    } catch (error) {
      setError(error.message || "Не удалось удалить сообщение");
    } finally {
      setDeletingMessage(false);
    }
  }, [deleteMessageCandidate, deletingMessage, setDeletingMessage, setError, request, selectedChat, setMessages, setDeleteMessageCandidate, setPersonalChats, setChats, notify]);

  const sendChatMessage = useCallback(async event => {
    event.preventDefault();
    if (!selectedChat || (!draft.trim() && !attachment)) return;
    try {
      let sentMessage;
      if (selectedChat.type === "personal") {
        if (attachment) throw new Error("В личных диалогах доступны только текстовые сообщения");
        sentMessage = await sendPersonalMessage(request, selectedChat.id, draft.trim());
      } else if (attachment) {
        sentMessage = await sendConversationAttachment(selectedChat.id, attachment, draft.trim());
      } else {
        sentMessage = await sendConversationText(request, selectedChat.id, draft.trim());
      }
      setDraft("");
      setAttachment(null);
      setMessages(await getChatMessages(request, selectedChat));
      if (selectedChat.type === "personal") setPersonalChats(await getPersonalConversations(request));
      else setChats(await getConversations(request));
      if (selectedChat.type === "personal") notify("Сообщение отправлено внутри UknowApp");
      else if (profile?.role === "admin" && sentMessage?.delivery_status !== "delivered") {
        notify("Сообщение сохранено. Подробности доставки доступны в переписке.");
      } else if (sentMessage?.delivery_status === "delivered" && profile?.role !== "teacher") {
        notify("Сообщение отправлено");
      }
    } catch (error) {
      setError(error.message);
    }
  }, [selectedChat, draft, attachment, request, setDraft, setAttachment, setMessages, setPersonalChats, setChats, notify, profile?.role, setError]);

  return { visibleChats, visibleMessages, openChat, createPersonalChat, confirmDeleteMessage, sendChatMessage };
}
