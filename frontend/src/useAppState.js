import { useRef, useState } from "react";

export function useAuthState() {
  const [auth, setAuth] = useState(() => localStorage.getItem("uknowapp-auth") === "1" || sessionStorage.getItem("uknowapp-auth") === "1" ? "1" : "");
  const [theme, setTheme] = useState(() => localStorage.getItem("uknowapp-theme-v2") || "dark-soft");
  const [profile, setProfile] = useState(null);
  const [login, setLogin] = useState("");
  const [password, setPassword] = useState("");
  return { auth, setAuth, theme, setTheme, profile, setProfile, login, setLogin, password, setPassword };
}

export function useGraphState() {
  const [teacherGraph, setTeacherGraph] = useState(null);
  const [collapsedTeacherIds, setCollapsedTeacherIds] = useState(() => new Set());
  return { teacherGraph, setTeacherGraph, collapsedTeacherIds, setCollapsedTeacherIds };
}

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

export function useDirectoryState() {
  const [users, setUsers] = useState([]);
  const [overview, setOverview] = useState(null);
  const [search, setSearch] = useState("");
  const [userSort, setUserSort] = useState("students");
  const [userInfo, setUserInfo] = useState(null);
  return { users, setUsers, overview, setOverview, search, setSearch, userSort, setUserSort, userInfo, setUserInfo };
}

export function useUserEditorState() {
  const [issuedCredential, setIssuedCredential] = useState(null);
  const [savingUser, setSavingUser] = useState(false);
  const [name, setName] = useState("");
  const [panelLogin, setPanelLogin] = useState("");
  const [role, setRole] = useState("teacher");
  const [telegramId, setTelegramId] = useState("");
  const [teacherId, setTeacherId] = useState("");
  const [studentId, setStudentId] = useState("");
  const [code, setCode] = useState(null);
  return {
    issuedCredential, setIssuedCredential, savingUser, setSavingUser,
    name, setName, panelLogin, setPanelLogin, role, setRole,
    telegramId, setTelegramId, teacherId, setTeacherId, studentId, setStudentId, code, setCode,
  };
}

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

export function useUiState() {
  const [page, setPage] = useState("graph");
  const [error, setError] = useState("");
  const [toast, setToast] = useState("");
  const [busy, setBusy] = useState(false);
  const [modal, setModal] = useState(null);
  return { page, setPage, error, setError, toast, setToast, busy, setBusy, modal, setModal };
}
