import { createSignal } from "solid-js";
export function createChatActionState() {
  const [deleteMessageCandidate, setDeleteMessageCandidate] = createSignal(null);
  const [deletingMessage, setDeletingMessage] = createSignal(false);
  const [deletePersonalChatCandidate, setDeletePersonalChatCandidate] = createSignal(null);
  const [deletingPersonalChat, setDeletingPersonalChat] = createSignal(false);
  return {
    get deleteMessageCandidate() {
      return deleteMessageCandidate();
    },
    setDeleteMessageCandidate,
    get deletingMessage() {
      return deletingMessage();
    },
    setDeletingMessage,
    get deletePersonalChatCandidate() {
      return deletePersonalChatCandidate();
    },
    setDeletePersonalChatCandidate,
    get deletingPersonalChat() {
      return deletingPersonalChat();
    },
    setDeletingPersonalChat,
  };
}
