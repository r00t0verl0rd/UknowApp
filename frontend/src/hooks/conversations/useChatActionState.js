import { useState } from "react";

export function useChatActionState() {
  const [deleteMessageCandidate, setDeleteMessageCandidate] = useState(null);
  const [deletingMessage, setDeletingMessage] = useState(false);
  return { deleteMessageCandidate, setDeleteMessageCandidate, deletingMessage, setDeletingMessage };
}
