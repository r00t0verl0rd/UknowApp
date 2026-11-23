import { createSignal } from "solid-js";
export function createPersonalChatState() {
  const [personalChats, setPersonalChats] = createSignal([]);
  const [chatSection, setChatSection] = createSignal("participants");
  return {
    get personalChats() {
      return personalChats();
    },
    setPersonalChats,
    get chatSection() {
      return chatSection();
    },
    setChatSection,
  };
}
