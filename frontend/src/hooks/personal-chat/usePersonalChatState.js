import { useState } from "react";

export function usePersonalChatState() {
  const [personalChats, setPersonalChats] = useState([]);
  const [chatSection, setChatSection] = useState("participants");
  return { personalChats, setPersonalChats, chatSection, setChatSection };
}
