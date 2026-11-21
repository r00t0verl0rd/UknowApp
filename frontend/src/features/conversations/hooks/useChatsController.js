import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useChatActionState } from "./useChatActionState.js";
import { markConversationMessageDeleted, mergeConversationMessages } from "../services/messageState.js";
import {
  createPersonalConversation, deleteChatMessage, getChatMessages,
  sendConversationAttachment,
  sendConversationText, sendPersonalMessage,
} from "../services/conversationsApi.js";

export function useChatsController({
  auth, request, profile, chatState, personalState, setPage, setError, setModal,
  notify,
}) {
  const { deleteMessageCandidate, deletingMessage, setDeletingMessage, setDeleteMessageCandidate } = useChatActionState();
  const [creating, setCreating] = useState(false);
  const sendingMessage = useRef(false);
  const pendingClientMessage = useRef(null);
  const activeChatKey = useRef("");
  const openingChatRequest = useRef(null);
  useEffect(() => () => openingChatRequest.current?.controller.abort(), []);
  const openChatRef = useRef(null);
  const {
    chats, setChats, selectedChat, setSelectedChat, messages, setMessages, setMessagesLoading,
    draft, setDraft, attachment, setAttachment, messagesViewportRef,
    chatSearch, chatFilter, messageFilter, setMessageFilter,
  } = chatState;
  const { personalChats, setPersonalChats, chatSection, setChatSection } = personalState;
  activeChatKey.current = selectedChat
    ? (selectedChat.type === "personal" ? "personal:" : "conversation:") + selectedChat.id
    : "";

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
    if (personal) setChatSection("personal");
    void openChatRef.current?.(chat);
  }, [auth, profile, personalChats, chats, setChatSection]);

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
    const chatKey = (chat.type === "personal" ? "personal:" : "conversation:") + chat.id;
    const previousRequest = openingChatRequest.current;
    if (activeChatKey.current === chatKey && previousRequest?.key === chatKey) return;
    previousRequest?.controller.abort();
    const controller = new AbortController();
    openingChatRequest.current = { key: chatKey, controller };
    activeChatKey.current = chatKey;
    setSelectedChat(chat);
    setMessages([]);
    setMessagesLoading(true);
    setPage("chats");
    setDraft("");
    setAttachment(null);
    setMessageFilter("all");
    try {
      const loadedMessages = await getChatMessages(request, chat, controller.signal);
      if (controller.signal.aborted || activeChatKey.current !== chatKey) return;
      // Preserve messages/status updates received over SSE while the initial
      // history request was in flight instead of replacing the live message list.
      setMessages(previous => mergeConversationMessages(previous, loadedMessages, chatKey));
    } catch (error) {
      if (!controller.signal.aborted && activeChatKey.current === chatKey) {
        openingChatRequest.current = null;
        setError(error.message);
      }
    } finally {
      if (!controller.signal.aborted && activeChatKey.current === chatKey) {
        setMessagesLoading(false);
      }
    }
  }, [setSelectedChat, setPage, setDraft, setAttachment, setMessageFilter, setMessages, setMessagesLoading, request, setError]);
  openChatRef.current = openChat;

  const openCreatePersonalChat = useCallback(() => {
    setModal({ mode: "create-personal" });
  }, [setError, setModal]);

  const createPersonalChat = useCallback(async userId => {
    if (creating) return;
    setCreating(true);
    try {
      let chat = personalChats.find(item => item.participant.id === userId);
      if (!chat) {
        chat = await createPersonalConversation(request, userId);
        setPersonalChats(current => current.some(item => item.id === chat.id) ? current : [chat, ...current]);
      }
      setModal(null);
      await openChat(chat);
    } catch (error) {
      setError(error.message);
    } finally {
      setCreating(false);
    }
  }, [creating, personalChats, request, setPersonalChats, setModal, openChat, setError]);

  const confirmDeleteMessage = useCallback(async () => {
    const message = deleteMessageCandidate;
    if (!message || deletingMessage) return;
    setDeletingMessage(true);
    try {
      const result = await deleteChatMessage(request, message, selectedChat?.type === "personal");
      const chatKey = (selectedChat?.type === "personal" ? "personal:" : "conversation:") + selectedChat?.id;
      markConversationMessageDeleted(chatKey, message.id);
      setMessages(current => current.filter(item => item.id !== message.id));
      setDeleteMessageCandidate(null);
      const messengerFailed = Number(result.messenger_failed ?? result.telegram_failed ?? 0);
      if (messengerFailed > 0) {
        setError("Сообщение удалено из UknowApp. Не удалось удалить копии во внешних мессенджерах: " + messengerFailed + ".");
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
    const chatKey = chat
      ? (chat.type === "personal" ? "personal:" : "conversation:") + chat.id
      : "";
    const text = draft.trim();
    const file = attachment;
    if (!chat || (!text && !file) || sendingMessage.current) return;

    sendingMessage.current = true;
    const optimistic = chat.type !== "personal" && !file && Boolean(text);
    const signature = [
      chat.type,
      chat.id,
      text,
      file?.name || "",
      file?.size || 0,
      file?.lastModified || 0,
    ].join(":");
    const pending = pendingClientMessage.current;
    const clientMessageId = (pending?.signature === signature ? pending.id : null)
      || (window.crypto?.randomUUID?.() || Date.now().toString(36) + Math.random().toString(36).slice(2));
    pendingClientMessage.current = { signature, id: clientMessageId };
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
        sentMessage = await sendPersonalMessage(request, chat.id, text, clientMessageId);
      } else if (file) {
        sentMessage = await sendConversationAttachment(chat.id, file, text, clientMessageId);
      } else {
        sentMessage = await sendConversationText(request, chat.id, text, clientMessageId);
      }

      pendingClientMessage.current = null;
      if (!optimistic) {
        setDraft("");
        setAttachment(null);
      }
      setMessages(current => mergeConversationMessages(current, [sentMessage], chatKey));

      if (chat.type !== "personal" && profile?.role === "admin") {
        const hasMessengerIssues = Object.values(sentMessage?.metadata?.messenger_deliveries || {})
          .some(delivery => (delivery?.errors || []).length > 0);
        if (hasMessengerIssues) setError("Сообщение доставлено в UknowApp. Подробности внешней доставки доступны в переписке.");
      }
    } catch (error) {
      if (clientMessageId) {
        setMessages(current => current.filter(item =>
          item.id !== optimisticId && item.metadata?.client_message_id !== clientMessageId
        ));
        setDraft(current => current || text);
      }
      setError(error.message);
    } finally {
      sendingMessage.current = false;
    }
  }, [selectedChat, draft, attachment, request, setDraft, setMessages, setAttachment, profile?.role, profile?.full_name, setError]);

  return { creating, visibleChats, visibleMessages, openChat, openCreatePersonalChat, createPersonalChat, confirmDeleteMessage, sendChatMessage, deleteMessageCandidate, deletingMessage, setDeleteMessageCandidate };
}
