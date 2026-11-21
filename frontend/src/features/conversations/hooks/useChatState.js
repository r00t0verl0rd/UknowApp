import { useRef, useState } from "react";

export function useChatState() {
  const [draft, setDraft] = useState("");
  const [attachment, setAttachment] = useState(null);
  const [chats, setChats] = useState([]);
  const [selectedChat, setSelectedChat] = useState(null);
  const [messages, setMessages] = useState([]);
  const [messagesLoading, setMessagesLoading] = useState(false);
  const messagesViewportRef = useRef(null);
  const [chatSearch, setChatSearch] = useState("");
  const [chatFilter, setChatFilter] = useState("all");
  const [messageFilter, setMessageFilter] = useState("all");
  return {
    draft, setDraft, attachment, setAttachment, chats, setChats,
    selectedChat, setSelectedChat, messages, setMessages, messagesLoading, setMessagesLoading, messagesViewportRef,
    chatSearch, setChatSearch, chatFilter, setChatFilter,
    messageFilter, setMessageFilter,
  };
}
