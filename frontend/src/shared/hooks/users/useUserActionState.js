import { useState } from "react";

export function useUserActionState() {
  const [deleteCandidate, setDeleteCandidate] = useState(null);
  const [deletingUser, setDeletingUser] = useState(false);
  const [disconnectCandidate, setDisconnectCandidate] = useState(null);
  const [unassignCandidate, setUnassignCandidate] = useState(null);
  const [unassigningStudent, setUnassigningStudent] = useState(false);
  const [disconnectingTelegram, setDisconnectingTelegram] = useState(false);
  return {
    deleteCandidate, setDeleteCandidate, deletingUser, setDeletingUser,
    disconnectCandidate, setDisconnectCandidate, disconnectingTelegram, setDisconnectingTelegram,
    unassignCandidate, setUnassignCandidate, unassigningStudent, setUnassigningStudent,
  };
}
