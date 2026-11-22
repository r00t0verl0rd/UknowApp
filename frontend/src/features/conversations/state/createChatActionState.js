import { createSignal } from "solid-js";
export function createChatActionState() {
  const [deleteMessageCandidate, setDeleteMessageCandidate] = createSignal(null);
  const [deletingMessage, setDeletingMessage] = createSignal(false);
  return {
    get deleteMessageCandidate() {
      return deleteMessageCandidate();
    },
    setDeleteMessageCandidate,
    get deletingMessage() {
      return deletingMessage();
    },
    setDeletingMessage,
  };
}
