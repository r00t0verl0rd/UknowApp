import { useRef, useState } from "react";

export function useChatState() {
  const [draft, setDraft] = useState("");
  const [attachment, setAttachment] = useState(null);
  const [chats, setChats] = useState([]);
  const [personalChats, setPersonalChats] = useState([]);
  const [chatSection, setChatSection] = useState("participants");
  const [selectedChat, setSelectedChat] = useState(null);
  const [messages, setMessages] = useState([]);
  const messagesViewportRef = useRef(null);
  const [chatSearch, setChatSearch] = useState("");
  const [chatFilter, setChatFilter] = useState("all");
  const [messageFilter, setMessageFilter] = useState("all");
  return {
    draft, setDraft, attachment, setAttachment, chats, setChats, personalChats, setPersonalChats, chatSection, setChatSection,
    selectedChat, setSelectedChat, messages, setMessages, messagesViewportRef,
    chatSearch, setChatSearch, chatFilter, setChatFilter,
    messageFilter, setMessageFilter,
  };
}
