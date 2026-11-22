import { createSignal } from "solid-js";
export function createUserActionState() {
  const [deleteCandidate, setDeleteCandidate] = createSignal(null);
  const [deletingUser, setDeletingUser] = createSignal(false);
  const [disconnectCandidate, setDisconnectCandidate] = createSignal(null);
  const [unassignCandidate, setUnassignCandidate] = createSignal(null);
  const [unassigningStudent, setUnassigningStudent] = createSignal(false);
  const [disconnectingTelegram, setDisconnectingTelegram] = createSignal(false);
  return {
    get deleteCandidate() {
      return deleteCandidate();
    },
    setDeleteCandidate,
    get deletingUser() {
      return deletingUser();
    },
    setDeletingUser,
    get disconnectCandidate() {
      return disconnectCandidate();
    },
    setDisconnectCandidate,
    get disconnectingTelegram() {
      return disconnectingTelegram();
    },
    setDisconnectingTelegram,
    get unassignCandidate() {
      return unassignCandidate();
    },
    setUnassignCandidate,
    get unassigningStudent() {
      return unassigningStudent();
    },
    setUnassigningStudent,
  };
}
