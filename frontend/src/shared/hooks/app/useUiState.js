import { useState } from "react";

export function useUiState() {
  const [page, setPage] = useState("graph");
  const [error, setError] = useState("");
  const [toast, setToast] = useState("");
  const [modal, setModal] = useState(null);
  return { page, setPage, error, setError, toast, setToast, modal, setModal };
}
