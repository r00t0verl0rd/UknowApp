import { createSignal } from "solid-js";
import { createConversationCache } from "../services/conversationCache.js";
export function createChatState() {
  const [draft, setDraft] = createSignal("");
  const [attachments, setAttachments] = createSignal([]);
  const [sendingAttachments, setSendingAttachments] = createSignal(false);
  const [chats, setChats] = createSignal([]);
  const [selectedChat, setSelectedChat] = createSignal(null);
  const [messages, setMessages] = createSignal([]);
  const [messagesLoading, setMessagesLoading] = createSignal(false);
  const [messagesViewport, setMessagesViewport] = createSignal(null);
  const messagesViewportRef = {
    get current() { return messagesViewport(); },
    set current(element) { setMessagesViewport(element); },
  };
  const [chatSearch, setChatSearch] = createSignal("");
  const [chatFilter, setChatFilter] = createSignal("all");
  const [messageFilter, setMessageFilter] = createSignal("all");
  return {
    cache: createConversationCache(),
    get draft() {
      return draft();
    },
    setDraft,
    get attachments() {
      return attachments();
    },
    setAttachments,
    get sendingAttachments() {
      return sendingAttachments();
    },
    setSendingAttachments,
    get chats() {
      return chats();
    },
    setChats,
    get selectedChat() {
      return selectedChat();
    },
    setSelectedChat,
    get messages() {
      return messages();
    },
    setMessages,
    get messagesLoading() {
      return messagesLoading();
    },
    setMessagesLoading,
    messagesViewportRef,
    get chatSearch() {
      return chatSearch();
    },
    setChatSearch,
    get chatFilter() {
      return chatFilter();
    },
    setChatFilter,
    get messageFilter() {
      return messageFilter();
    },
    setMessageFilter,
  };
}
