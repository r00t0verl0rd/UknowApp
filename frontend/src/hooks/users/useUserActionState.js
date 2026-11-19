import { useRef, useState } from "react";

export function useUserActionState() {
  const [deleteCandidate, setDeleteCandidate] = useState(null);
  const [deletingUser, setDeletingUser] = useState(false);
  const [deleteMessageCandidate, setDeleteMessageCandidate] = useState(null);
  const [deletingMessage, setDeletingMessage] = useState(false);
  const [disconnectCandidate, setDisconnectCandidate] = useState(null);
  const [disconnectingTelegram, setDisconnectingTelegram] = useState(false);
  return {
    deleteCandidate, setDeleteCandidate, deletingUser, setDeletingUser,
    deleteMessageCandidate, setDeleteMessageCandidate, deletingMessage, setDeletingMessage,
    disconnectCandidate, setDisconnectCandidate, disconnectingTelegram, setDisconnectingTelegram,
  };
}
