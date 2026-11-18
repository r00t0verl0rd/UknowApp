import { useCallback, useEffect, useLayoutEffect, useMemo, useState } from "react";
import { useAuthState, useChatState, useDirectoryState, useGraphState, useUiState, useUserActionState, useUserEditorState } from "./useAppState.js";
import Activity from "lucide-react/dist/esm/icons/activity.js";
import ArrowLeft from "lucide-react/dist/esm/icons/arrow-left.js";
import Check from "lucide-react/dist/esm/icons/check.js";
import ChevronRight from "lucide-react/dist/esm/icons/chevron-right.js";
import GraduationCap from "lucide-react/dist/esm/icons/graduation-cap.js";
import LogOut from "lucide-react/dist/esm/icons/log-out.js";
import MessageCircle from "lucide-react/dist/esm/icons/message-circle.js";
import Pencil from "lucide-react/dist/esm/icons/pencil.js";
import Plus from "lucide-react/dist/esm/icons/plus.js";
import RefreshCw from "lucide-react/dist/esm/icons/refresh-cw.js";
import Search from "lucide-react/dist/esm/icons/search.js";
import Trash2 from "lucide-react/dist/esm/icons/trash-2.js";
import Users from "lucide-react/dist/esm/icons/users.js";
import X from "lucide-react/dist/esm/icons/x.js";
import Copy from "lucide-react/dist/esm/icons/copy.js";
import Unlink from "lucide-react/dist/esm/icons/unlink.js";
import Paperclip from "lucide-react/dist/esm/icons/paperclip.js";
import Moon from "lucide-react/dist/esm/icons/moon.js";
import Sun from "lucide-react/dist/esm/icons/sun.js";
import Smile from "lucide-react/dist/esm/icons/smile.js";
import Link2 from "lucide-react/dist/esm/icons/link-2.js";
import Info from "lucide-react/dist/esm/icons/info.js";
import DatabaseIcon from "lucide-react/dist/esm/icons/database.js";
import ArchiveIcon from "lucide-react/dist/esm/icons/archive.js";
import MessageBubble from "./MessageBubble.jsx";

const API = import.meta.env.VITE_API_BASE_URL || "";
function formatBytes(bytes) {
  if (!bytes) return "0 Б";
  const units = ["Б", "КБ", "МБ", "ГБ", "ТБ"];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return (bytes / (1024 ** index)).toLocaleString("ru-RU", { maximumFractionDigits: index ? 1 : 0 }) + " " + units[index];
}

async function copyText(value) {
  try {
    if (window.isSecureContext && navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(value);
      return true;
    }
  } catch {
    // Clipboard API may be unavailable or denied; use the browser fallback.
  }

  const textarea = document.createElement("textarea");
  textarea.value = value;
  textarea.setAttribute("readonly", "");
  textarea.style.position = "fixed";
  textarea.style.opacity = "0";
  textarea.style.pointerEvents = "none";
  document.body.appendChild(textarea);
  textarea.select();
  textarea.setSelectionRange(0, textarea.value.length);
  let copied = false;
  try {
    copied = document.execCommand("copy");
  } catch {
    copied = false;
  }
  textarea.remove();
  return copied;
}

// Главный экран панели: здесь хранятся состояние разделов, данные API и действия пользователя.
export default function App() {
  const {
    auth, setAuth, theme, setTheme, profile, setProfile, login, setLogin, password, setPassword,
  } = useAuthState();
  const {
    teacherGraph, setTeacherGraph, collapsedTeacherIds, setCollapsedTeacherIds,
  } = useGraphState();
  const {
    draft, setDraft, attachment, setAttachment, chats, setChats, personalChats, setPersonalChats, chatSection, setChatSection,
    selectedChat, setSelectedChat, messages, setMessages, messagesViewportRef,
    chatSearch, setChatSearch, chatFilter, setChatFilter,
    messageFilter, setMessageFilter,
  } = useChatState();
  const {
    users, setUsers, overview, setOverview, search, setSearch, userSort, setUserSort, userInfo, setUserInfo,
  } = useDirectoryState();
  const {
    issuedCredential, setIssuedCredential, savingUser, setSavingUser,
    name, setName, panelLogin, setPanelLogin, role, setRole, additionalInfo, setAdditionalInfo,
    telegramId, setTelegramId, teacherId, setTeacherId, studentId, setStudentId, code, setCode,
  } = useUserEditorState();
  const {
    deleteCandidate, setDeleteCandidate, deletingUser, setDeletingUser,
    deleteMessageCandidate, setDeleteMessageCandidate, deletingMessage, setDeletingMessage,
    disconnectCandidate, setDisconnectCandidate, disconnectingTelegram, setDisconnectingTelegram,
  } = useUserActionState();
  const {
    page, setPage, error, setError, toast, setToast, busy, setBusy, modal, setModal,
  } = useUiState();
  const [dataStats, setDataStats] = useState(null);
  const [dataBusy, setDataBusy] = useState(false);
  const [retentionDays, setRetentionDays] = useState("30");

  useEffect(() => {
    if (userInfo === null) return undefined;
    const closeInfoOnOutsideClick = event => {
      if (!event.target.closest?.(".user-info-wrap")) setUserInfo(null);
    };
    const closeInfoOnEscape = event => {
      if (event.key === "Escape") setUserInfo(null);
    };
    document.addEventListener("pointerdown", closeInfoOnOutsideClick);
    document.addEventListener("keydown", closeInfoOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeInfoOnOutsideClick);
      document.removeEventListener("keydown", closeInfoOnEscape);
    };
  }, [userInfo]);
  // Единая точка HTTP-запросов: добавляет cookie-сессию и приводит ошибки API к понятному сообщению.
  const request = useCallback(async (path, options = {}) => {
    const response = await fetch(API + path, {
      ...options,
      credentials: "include",
      headers: { "Content-Type": "application/json", ...(options.headers || {}) }
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = Array.isArray(data.detail)
        ? data.detail.map(item => {
            const field = Array.isArray(item.loc) ? item.loc[item.loc.length - 1] : "";
            return (field ? field + ": " : "") + (item.msg || "Некорректное значение");
          }).join("; ")
        : (typeof data.detail === "string" ? data.detail : "Ошибка запроса");
      throw new Error(detail);
    }
    return data;
  }, []);

  // Загружает актуальные данные панели в зависимости от роли вошедшего пользователя.
  const refresh = useCallback(async () => {
    if (!auth) return;
    setBusy(true); setError("");
    try {
      const who = await request("/api/panel/me");
      setProfile(who);

      // Independent panel datasets are fetched together to avoid serial network waits.
      const roleRequest = who.role === "admin"
        ? Promise.all([request("/api/admin/users"), request("/api/admin/overview")])
        : who.role === "teacher" ? request("/api/panel/graph") : Promise.resolve(null);
      const [conversations, roleData, personal] = await Promise.all([
        request("/api/panel/conversations"), roleRequest, request("/api/panel/personal-conversations"),
      ]);
      setChats(conversations); setPersonalChats(personal);
      if (who.role === "admin") {
        const [people, summary] = roleData;
        setUsers(people); setOverview(summary);
      } else if (who.role === "teacher") {
        setTeacherGraph(roleData);
        setUsers([]); setOverview(null);
      } else {
        setTeacherGraph(null); setUsers([]); setOverview(null);
        setPage("chats");
        // Keep the inbox visible on entry. Fetching messages marks them read,
        // so only an explicit student click should clear the unread counter.
        setSelectedChat(null);
        setMessages([]);
      }
    } catch (e) {
      setError(e.message);
      if (["учитель", "ученик", "логин", "сессия", "войдите", "учётная запись"].some(term => String(e.message).toLowerCase().includes(term)) || String(e.message).includes("401")) {
        localStorage.removeItem("uknowapp-auth"); sessionStorage.removeItem("uknowapp-auth");
        setAuth("");
        setProfile(null);
      }
    } finally { setBusy(false); }
  }, [auth, request]);

  useEffect(() => { refresh(); }, [refresh]);

  useEffect(() => {
    localStorage.setItem("uknowapp-theme-v2", theme);
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  // В разделе переписок события SSE сообщают об изменениях; периодический опрос не нужен.
  useEffect(() => {
    if (!auth || page !== "chats") return undefined;
    let active = true;
    let inFlight = false;
    let refreshPending = false;
    let refreshMessagesPending = false;

    const syncChats = async (event, forceMessages = false) => {
      if (!active) return;
      let shouldRefreshMessages = forceMessages;
      if (event) {
        let eventConversationId = null;
        if (event.data) {
          try {
            eventConversationId = Number(JSON.parse(event.data).conversation_id) || null;
          } catch {
            // An empty or malformed event is treated as a general refresh.
          }
        }
        shouldRefreshMessages = !eventConversationId
          || eventConversationId === Number(selectedChat?.id);
      }
      if (inFlight) {
        refreshPending = true;
        refreshMessagesPending ||= Boolean(selectedChat?.id && shouldRefreshMessages);
        return;
      }
      inFlight = true;
      try {
        if (selectedChat?.id && shouldRefreshMessages) {
          const rows = await request((selectedChat.type === "personal" ? "/api/panel/personal-conversations/" : "/api/panel/conversations/") + selectedChat.id + "/messages");
          if (!active) return;
          setMessages(rows);
        }
        // Loading messages marks them read for teachers. Fetch the list after
        // that write so unread counters are correct in the same refresh cycle.
        const [conversations, personal] = await Promise.all([request("/api/panel/conversations"), request("/api/panel/personal-conversations")]);
        if (!active) return;
        setChats(conversations); setPersonalChats(personal);
      } catch {
        // Keep the current conversation visible during brief network interruptions.
      } finally {
        inFlight = false;
        if (refreshPending && active) {
          const reloadMessages = refreshMessagesPending;
          refreshPending = false;
          refreshMessagesPending = false;
          void syncChats(null, reloadMessages);
        }
      }
    };

    // One persistent SSE connection replaces the two-second HTTP polling loop.
    // The server sends an initial update event as soon as the stream is ready.
    const eventSource = new EventSource(API + "/api/panel/events", { withCredentials: true });
    eventSource.addEventListener("update", syncChats);

    const onVisibilityChange = () => {
      if (document.visibilityState === "visible") void syncChats(null, true);
    };
    document.addEventListener("visibilitychange", onVisibilityChange);

    return () => {
      active = false;
      eventSource.close();
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
  }, [auth, page, selectedChat?.id, request]);

  const notify = (message) => { setToast(message); window.setTimeout(() => setToast(""), 2600); };
  const loadDataStats = useCallback(async () => {
    try {
      setDataStats(await request("/api/admin/data/stats"));
    } catch (e) {
      setError(e.message);
    }
  }, [request]);

  useEffect(() => {
    if (auth && profile?.role === "admin" && page === "additional") void loadDataStats();
  }, [auth, profile?.role, page, loadDataStats]);

  async function downloadAdminFile(kind) {
    try {
      const response = await fetch(API + "/api/admin/data/" + kind, { credentials: "include" });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.detail || "Не удалось скачать файл");
      }
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = kind === "database" ? "uknowapp-backup.sqlite3" : "uknowapp-dialogues.zip";
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      notify("Файл подготовлен к скачиванию");
    } catch (e) {
      setError(e.message);
    }
  }

  async function uploadAdminFile(kind, file) {
    if (!file) return;
    const warning = kind === "database"
      ? "Заменить текущую базу данных загруженной копией? Все текущие данные будут перезаписаны."
      : "Заменить текущую историю сообщений архивом? Текущие сообщения и медиафайлы будут заменены.";
    if (!window.confirm(warning)) return;
    setDataBusy(true);
    setError("");
    try {
      const form = new FormData();
      form.append("file", file);
      const response = await fetch(API + "/api/admin/data/" + kind, {
        method: "POST", credentials: "include", body: form,
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || "Не удалось загрузить файл");
      notify(kind === "database" ? "База данных восстановлена. Перезагрузите панель." : "Архив переписок восстановлен");
      await loadDataStats();
      if (kind === "dialogues") {
        setSelectedChat(null);
        setMessages([]);
        await refresh();
      }
    } catch (e) {
      setError(e.message);
    } finally {
      setDataBusy(false);
    }
  }

  async function cleanupOldDialogues() {
    const days = Number(retentionDays);
    if (!window.confirm("Удалить переписки и медиафайлы старше " + days + " дней? Действие необратимо.")) return;
    setDataBusy(true);
    setError("");
    try {
      const result = await request("/api/admin/data/dialogues?days=" + days, { method: "DELETE" });
      notify("Удалено сообщений: " + result.deleted_messages + ", личных: " + result.deleted_personal_messages + ", медиафайлов: " + result.deleted_media_files);
      await loadDataStats();
      await refresh();
    } catch (e) {
      setError(e.message);
    } finally {
      setDataBusy(false);
    }
  }

  // Списки участников пересчитываются только при изменении массива пользователей.
  const activeTeachers = useMemo(() => users.filter(u => u.active && u.role === "teacher"), [users]);
  const activeStudents = useMemo(() => users.filter(u => u.active && u.role === "student"), [users]);
  const studentsByTeacherId = useMemo(
    () => new Map((overview?.teachers || []).map(teacher => [teacher.id, teacher.students || []])),
    [overview]
  );
  const visibleUsers = useMemo(() => users
    .filter(u => (u.full_name + " " + (u.telegram_id || "")).toLowerCase().includes(search.toLowerCase()))
    .sort((a, b) => {
      if (userSort === "teachers") return (a.role === "teacher" ? 0 : 1) - (b.role === "teacher" ? 0 : 1) || a.full_name.localeCompare(b.full_name, "ru");
      if (userSort === "students") return (a.role === "student" ? 0 : 1) - (b.role === "student" ? 0 : 1) || a.full_name.localeCompare(b.full_name, "ru");
      if (userSort === "active") return Number(b.active) - Number(a.active) || a.full_name.localeCompare(b.full_name, "ru");
      if (userSort === "inactive") return Number(a.active) - Number(b.active) || a.full_name.localeCompare(b.full_name, "ru");
      return a.full_name.localeCompare(b.full_name, "ru", { sensitivity: "base" }) * (userSort === "name-desc" ? -1 : 1);
    }), [users, search, userSort]);
  // Один раз собираем ID уже назначенных учеников, чтобы быстро найти свободных.
  const assignedStudentIds = useMemo(() => new Set((overview?.teachers || []).flatMap(t => t.students.map(s => s.id))), [overview]);
  const unassignedStudents = useMemo(() => activeStudents.filter(student => !assignedStudentIds.has(student.id)), [activeStudents, assignedStudentIds]);
  const visibleMessages = useMemo(() => messages.filter(message => {
    const kind = message.metadata?.media?.kind || message.content_type;
    if (messageFilter === "all") return true;
    if (messageFilter === "media") return kind !== "text" || Boolean(message.metadata?.media);
    if (messageFilter === "audio") return ["voice", "audio"].includes(kind);
    if (messageFilter === "photos") return kind === "photo";
    if (messageFilter === "files") return ["document", "video", "video_note", "video_sticker", "animation", "animated_sticker", "sticker"].includes(kind);
    return true;
  }), [messages, messageFilter]);

  useLayoutEffect(() => {
    const viewport = messagesViewportRef.current;
    if (!viewport) return undefined;

    const scrollToLatest = () => {
      // New messages are appended at the bottom, directly above the composer.
      viewport.scrollTop = viewport.scrollHeight;
    };

    scrollToLatest();
    const frame = window.requestAnimationFrame(scrollToLatest);

    // Keep the bottom in view when an attachment finishes loading and changes
    // the height of an existing message (for example, audio/video metadata).
    const resizeObserver = typeof ResizeObserver !== "undefined"
      ? new ResizeObserver(scrollToLatest)
      : null;
    const observeMessages = () => {
      if (!resizeObserver) return;
      Array.from(viewport.children).forEach(child => resizeObserver.observe(child));
    };
    observeMessages();

    const mutationObserver = typeof MutationObserver !== "undefined"
      ? new MutationObserver(() => {
          observeMessages();
          scrollToLatest();
        })
      : null;
    mutationObserver?.observe(viewport, { childList: true });

    return () => {
      window.cancelAnimationFrame(frame);
      resizeObserver?.disconnect();
      mutationObserver?.disconnect();
    };
  }, [selectedChat?.id, messageFilter, visibleMessages]);

  const visibleChats = useMemo(() => {
    const query = chatSearch.trim().toLocaleLowerCase("ru");
    const personal = personalChats.filter(chat => (!query || chat.title.toLocaleLowerCase("ru").includes(query)) && (chatFilter === "all" || Number(chat.unread_count || 0) > 0));
    if (profile?.role === "admin" && chatSection === "personal") return personal;
    const regular = profile?.role === "student" ? chats.slice(0, 1) : chats.filter(chat => {
      const names = profile?.role === "admin"
        ? chat.teacher.full_name + " " + chat.student.full_name
        : chat.student.full_name + " " + chat.teacher.full_name;
      const matchesSearch = !query || names.toLocaleLowerCase("ru").includes(query);
      const matchesFilter = profile?.role !== "teacher" || chatFilter === "all" || Number(chat.unread_count || 0) > 0;
      return matchesSearch && matchesFilter;
    });
    return profile?.role === "admin" ? regular : [...regular, ...personal];
  }, [chats, personalChats, chatSection, chatSearch, chatFilter, profile?.role]);

  function toggleTheme() {
    setTheme(current => current === "dark-soft" ? "light" : "dark-soft");
  }

  async function signIn(event) {
    event.preventDefault();
    setError("");

    if (!login.trim()) {
      setError("Введите логин");
      return;
    }
    if (!password) {
      setError("Введите пароль");
      return;
    }

    try {
      const response = await fetch(API + "/api/auth/login", { method: "POST", credentials: "include", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ username: login.trim(), password }) });
      const result = await response.json().catch(() => ({}));
      if (!response.ok) {
        const detail = Array.isArray(result.detail)
          ? result.detail.map(item => item.msg || "Некорректные данные").join("; ")
          : typeof result.detail === "string" ? result.detail : "Не удалось войти";
        throw new Error(detail);
      }
      localStorage.setItem("uknowapp-auth", "1"); sessionStorage.removeItem("uknowapp-auth"); setProfile(result); setPage(result.role === "student" ? "chats" : "graph"); setAuth("1"); setPassword("");
    } catch (e) {
      setError(e.message || "Не удалось войти");
    }
  }

  async function signOut() {
    try {
      await fetch(API + "/api/auth/logout", { method: "POST", credentials: "include" });
    } catch {
      // Clear the local view even when the server is temporarily unreachable.
    }
    localStorage.removeItem("uknowapp-auth"); sessionStorage.removeItem("uknowapp-auth"); setAuth(""); setProfile(null); setTeacherGraph(null); setUsers([]); setOverview(null); setChats([]); setPersonalChats([]); setMessages([]); setSelectedChat(null); setDraft(""); setAttachment(null); setIssuedCredential(null);
  }

  function openCreatePersonalChat() {
    setError("");
    setModal({ mode: "create-personal" });
  }

  function openCreate(defaultRole = "student") {
    setIssuedCredential(null); setModal({ mode: "create", id: null }); setName(""); setPanelLogin(""); setRole(defaultRole); setAdditionalInfo(""); setTelegramId(""); setError("");
  }
  function openEdit(user) {
    setModal({ mode: "edit", id: user.id }); setName(user.full_name); setPanelLogin(user.web_username || user.full_name); setRole(user.role); setAdditionalInfo(user.additional_info || ""); setTelegramId(user.telegram_id ? String(user.telegram_id) : ""); setError("");
  }

  async function saveUser(event) {
    event.preventDefault();
    setSavingUser(true);
    setError("");
    const body = { full_name: name.trim(), role, telegram_id: telegramId.trim() ? Number(telegramId) : null };
    if (role === "student") body.additional_info = additionalInfo.trim();
    if (role === "teacher" || role === "student") body.web_username = (panelLogin || name).trim();
    try {
      const saved = modal.mode === "create"
        ? await request("/api/admin/users", { method: "POST", body: JSON.stringify(body) })
        : await request("/api/admin/users/" + modal.id, { method: "PATCH", body: JSON.stringify(body) });
      setModal(null);
      await refresh();
      if (saved.issued_access_code) {
        setIssuedCredential({
          full_name: saved.full_name,
          username: saved.web_username || saved.full_name,
          code: saved.issued_access_code,
          role: saved.role,
        });
      } else {
        notify(modal.mode === "create" ? "Участник добавлен" : "Изменения сохранены");
      }
    } catch (e) {
      setError(e.message || "Не удалось сохранить профиль");
    } finally {
      setSavingUser(false);
    }
  }

  async function regeneratePanelAccessCode() {
    if (!modal || modal.mode !== "edit" || !["teacher", "student"].includes(role)) return;
    setSavingUser(true);
    setError("");
    try {
      const issued = await request("/api/admin/users/" + modal.id + "/access-code", { method: "POST" });
      // Show the issued code immediately; refreshing the rest of the panel is non-blocking.
      setIssuedCredential({
        full_name: issued.full_name,
        username: issued.web_username || issued.full_name,
        code: issued.issued_access_code,
        role: issued.role,
      });
      void refresh();
    } catch (e) {
      setError(e.message || "Не удалось создать новый код доступа");
    } finally {
      setSavingUser(false);
    }
  }

  function removeUser(user) {
    setDeleteCandidate(user);
  }

  async function confirmRemoveUser() {
    const user = deleteCandidate;
    if (!user || deletingUser) return;
    setDeletingUser(true);
    setError("");
    try {
      await request("/api/admin/users/" + user.id, { method: "DELETE" });
      if (selectedChat && (selectedChat.teacher.id === user.id || selectedChat.student.id === user.id)) {
        setSelectedChat(null);
        setMessages([]);
      }
      setDeleteCandidate(null);
      if (modal?.mode === "edit" && modal.id === user.id) setModal(null);
      await refresh();
      notify("Пользователь удалён");
    } catch (e) {
      setError(e.message);
    } finally {
      setDeletingUser(false);
    }
  }

  async function assign(event) {
    event.preventDefault();
    try {
      await request("/api/admin/assignments", { method: "POST", body: JSON.stringify({ teacher_id: Number(teacherId), student_id: Number(studentId) }) });
      setModal(null); await refresh(); notify("Ученик назначен учителю");
    } catch (e) { setError(e.message); }
  }

  function disconnectTelegram(user) {
    setDisconnectCandidate(user);
  }

  async function confirmDisconnectTelegram() {
    const user = disconnectCandidate;
    if (!user || disconnectingTelegram) return;
    setDisconnectingTelegram(true);
    setError("");
    try {
      await request("/api/admin/users/" + user.id + "/disconnect-telegram", { method: "POST" });
      setDisconnectCandidate(null);
      await refresh();
      notify("Telegram отключён");
    } catch (e) { setError(e.message); }
    finally { setDisconnectingTelegram(false); }
  }

  async function makeCode(user) {
    try {
      const result = await request("/api/admin/users/" + user.id + "/connection-code", { method: "POST" });
      setCode({ ...result, full_name: user.full_name }); 
    } catch (e) { setError(e.message); }
  }

  async function openChat(chat) {
    setSelectedChat(chat); setPage("chats"); setDraft(""); setAttachment(null); setMessageFilter("all");
    try {
      const base = chat.type === "personal" ? "/api/panel/personal-conversations/" : "/api/panel/conversations/";
      setMessages(await request(base + chat.id + "/messages"));
      if (chat.type === "personal") setPersonalChats(await request("/api/panel/personal-conversations"));
      else if (profile?.role === "teacher") setChats(await request("/api/panel/conversations"));
    } catch (e) { setError(e.message); }
  }

  async function createPersonalChat(userId) {
    try {
      const chat = await request("/api/panel/personal-conversations", { method: "POST", body: JSON.stringify({ user_id: Number(userId) }) });
      setPersonalChats(await request("/api/panel/personal-conversations"));
      setChatSection("personal");
      setModal(null);
      await openChat(chat);
    } catch (e) { setError(e.message); }
  }

  async function confirmDeleteMessage() {
    const message = deleteMessageCandidate;
    if (!message || deletingMessage) return;
    setDeletingMessage(true);
    setError("");
    try {
      const result = selectedChat?.type === "personal" ? await request("/api/panel/personal-messages/" + message.id, { method: "DELETE" }) : await request("/api/panel/messages/" + message.id, { method: "DELETE" });
      setMessages(current => current.filter(item => item.id !== message.id));
      setDeleteMessageCandidate(null);
      if (selectedChat?.type === "personal") setPersonalChats(await request("/api/panel/personal-conversations"));
      else if (selectedChat) setChats(await request("/api/panel/conversations"));
      if (result.telegram_failed > 0) {
        notify("Удалено из UknowApp. Не удалось удалить копии в Telegram: " + result.telegram_failed + ". Возможно, Telegram уже не разрешает их удаление.");
      } else {
        notify("Сообщение удалено у всех участников");
      }
    } catch (e) {
      setError(e.message || "Не удалось удалить сообщение");
    } finally {
      setDeletingMessage(false);
    }
  }

  async function sendChatMessage(event) {
    event.preventDefault();
    if (!selectedChat || (!draft.trim() && !attachment)) return;
    try {
      let sentMessage;
      if (selectedChat.type === "personal") {
        if (attachment) throw new Error("В личных диалогах доступны только текстовые сообщения");
        sentMessage = await request("/api/panel/personal-conversations/" + selectedChat.id + "/messages", { method: "POST", body: JSON.stringify({ text: draft.trim() }) });
      } else if (attachment) {
        const form = new FormData();
        form.append("file", attachment);
        form.append("text", draft.trim());
        const response = await fetch(API + "/api/panel/conversations/" + selectedChat.id + "/attachments", {
          method: "POST",
          credentials: "include",
          body: form
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.detail || "Не удалось отправить файл");
        sentMessage = data;
      } else {
        sentMessage = await request("/api/panel/conversations/" + selectedChat.id + "/messages", {
          method: "POST", body: JSON.stringify({ text: draft.trim() })
        });
      }
      setDraft(""); setAttachment(null);
      setMessages(await request((selectedChat.type === "personal" ? "/api/panel/personal-conversations/" : "/api/panel/conversations/") + selectedChat.id + "/messages"));
      if (selectedChat.type === "personal") setPersonalChats(await request("/api/panel/personal-conversations"));
      else setChats(await request("/api/panel/conversations"));
      if (selectedChat.type === "personal") notify("Сообщение отправлено внутри UknowApp");
      else if (profile?.role === "admin" && sentMessage?.delivery_status !== "delivered") {
        notify("Сообщение сохранено. Подробности доставки доступны в переписке.");
      } else if (sentMessage?.delivery_status === "delivered" && profile?.role !== "teacher") {
        notify("Сообщение отправлено");
      }
    } catch (e) { setError(e.message); }
  }

  if (!auth) return <div className="login-screen">
    <div className="login-card">
      <button type="button" className="theme-toggle login-theme-toggle" onClick={toggleTheme} title={theme === "dark-soft" ? "Светлая тема" : "Тёмная soft-тема"} aria-label={theme === "dark-soft" ? "Включить светлую тему" : "Включить тёмную soft-тему"}>
        {theme === "dark-soft" ? <Sun size={17}/> : <Moon size={17}/>}
      </button>
      <img src="/logo.png" alt="UknowApp" className="login-logo" />
      <h1>UknowApp</h1>
      <form onSubmit={signIn} className="stack">
        <label><input value={login} onChange={e => setLogin(e.target.value)} autoComplete="username" placeholder="Логин" aria-label="Логин" /></label>
        <label><input type="password" value={password} onChange={e => setPassword(e.target.value)} autoComplete="current-password" placeholder="Пароль" aria-label="Пароль" /></label>
        {error && <div className="alert">{error}</div>}
        <button className="btn primary" type="submit">Войти <ChevronRight size={17}/></button>
      </form>
    </div>
  </div>;

  return <div className="shell chats-shell">
    <aside className="sidebar">
      <div className="brand"><img src="/logo.png" alt="" /><span>Uknow<span>App</span></span></div>
      <div className="school-label">{profile?.role === "admin" ? "УПРАВЛЕНИЕ ШКОЛОЙ" : profile?.role === "student" ? "ЛИЧНЫЙ КАБИНЕТ УЧЕНИКА" : "РАБОЧЕЕ МЕСТО УЧИТЕЛЯ"}</div>
      <nav>
        {profile?.role !== "student" && <>
          <button className={page === "graph" ? "active" : ""} onClick={() => setPage("graph")}><Activity/>Структура</button>
          {profile?.role === "admin" && <button className={page === "users" ? "active" : ""} onClick={() => setPage("users")}><Users/>Пользователи</button>}
        </>}
        <button className={page === "chats" ? "active" : ""} onClick={() => setPage("chats")}><MessageCircle/>Диалоги</button>
      </nav>
      <div className="sidebar-bottom">
        {profile?.role === "admin" && <button type="button" className={`logout desktop-admin-extra${page === "additional" ? " active" : ""}`} onClick={() => setPage("additional")}><Info size={18}/>Дополнительно</button>}
        <button className="logout desktop-logout" onClick={signOut} title="Выйти" aria-label="Выйти"><LogOut/>Выйти</button>
        <div className="mobile-quick-actions">
          <button type="button" className="theme-toggle" onClick={toggleTheme} title={theme === "dark-soft" ? "Светлая тема" : "Тёмная soft-тема"} aria-label={theme === "dark-soft" ? "Включить светлую тему" : "Включить тёмную soft-тему"}>
            {theme === "dark-soft" ? <Sun size={17}/> : <Moon size={17}/>}
          </button>
          <button type="button" className="icon-btn" onClick={refresh} title="Обновить" aria-label="Обновить"><RefreshCw className={busy ? "spin" : ""}/></button>
          <button className="logout" onClick={signOut} title="Выйти" aria-label="Выйти"><LogOut/></button>
        </div>
      </div>
    </aside>

    <main className="main chats-main">
      <header className="topbar">
        <small className="topbar-user">{profile?.full_name}</small>
        <div className="topbar-actions">
          <button type="button" className="theme-toggle" onClick={toggleTheme} title={theme === "dark-soft" ? "Светлая тема" : "Тёмная soft-тема"} aria-label={theme === "dark-soft" ? "Включить светлую тему" : "Включить тёмную soft-тему"}>
            {theme === "dark-soft" ? <Sun size={17}/> : <Moon size={17}/>}
          </button>
          <button type="button" className="icon-btn" onClick={refresh} title="Обновить" aria-label="Обновить"><RefreshCw className={busy ? "spin" : ""}/></button>
        </div>
      </header>
      <div className={"content" + (page === "chats" ? " chats-content" : "")}>
        {error && <div className="alert alert-row">{error}<button onClick={() => setError("")}><X/></button></div>}
        {page === "graph" && profile?.role === "teacher" && <section className="teacher-readonly-graph">
          <div className="teacher-graph-root">
            <div className="teacher-graph-card">
              <div className="avatar teacher-avatar"><GraduationCap/></div>
              <div><b>{teacherGraph?.teacher.full_name || profile?.full_name}</b><small>Вы · Учитель</small></div>
              <span className="readonly-tag">Ваша группа</span>
            </div>
            <div className="teacher-graph-students">
              <div className="teacher-graph-connector"/>
              <div className="teacher-graph-student-grid">
                {(teacherGraph?.students || []).map(student => <div className="teacher-graph-card student" key={student.id}>
                  <div className="avatar student-avatar"><Smile/></div>
                  <div><b>{student.full_name}</b>{student.additional_info && <small className="student-additional-info">{student.additional_info}</small>}</div>
                </div>)}
              </div>
              {!(teacherGraph?.students || []).length && <div className="empty-state">Пока нет назначенных учеников</div>}
            </div>
          </div>
        </section>}
        {page === "graph" && profile?.role === "admin" && <>
          <section className="graph-panel">
            <div className="graph-legend-row">
              <div className="legend graph-legend">
                <div className="graph-legend-item"><span className="teacher-dot"/>Учителя <b>{overview?.counts.teachers || 0}</b></div>
                <div className="graph-legend-item"><span className="student-dot"/>Ученики <b>{overview?.counts.students || 0}</b></div>
              </div>
              <button className="btn primary graph-add-participant" onClick={() => openCreate()}><Plus/>Добавить участника</button>
            </div>
            <div className="root-node"><img src="/logo.png" alt=""/><div><b>Администратор</b><small>Полное управление</small></div></div>
            <div className="teacher-grid">
              {activeTeachers.map(teacher => {
                const students = studentsByTeacherId.get(teacher.id) || [];
                const studentsCollapsed = collapsedTeacherIds.has(teacher.id);
                return <section className={`teacher-branch${studentsCollapsed ? " is-collapsed" : ""}`} key={teacher.id}>
                <div className="person-card teacher-card">
                  <div className="person-main"><div className="avatar teacher-avatar"><GraduationCap/></div><div className="person-info"><b>{teacher.full_name}</b><small>Учитель · {students.length} учен.</small></div></div>
                  <div className="person-actions">
                    <button className={`danger-icon teacher-collapse-btn${studentsCollapsed ? "" : " is-expanded"}`} title={studentsCollapsed ? "Показать учеников" : "Скрыть учеников"} aria-label={studentsCollapsed ? "Показать учеников" : "Скрыть учеников"} aria-expanded={!studentsCollapsed} onClick={() => setCollapsedTeacherIds(current => { const next = new Set(current); if (next.has(teacher.id)) next.delete(teacher.id); else next.add(teacher.id); return next; })}><ChevronRight/></button>
                    <button title="Редактировать" onClick={() => openEdit(teacher)}><Pencil/></button>
                  </div>
                </div>
                {!studentsCollapsed && <button className="add-student" onClick={() => { setTeacherId(String(teacher.id)); setStudentId(activeStudents[0]?.id ? String(activeStudents[0].id) : ""); setModal({ mode: "assign" }); }}><Plus/>Назначить ученика</button>}
                {!studentsCollapsed && <div className="student-list">
                  {students.map(student => <div className="person-card student-card" key={student.id}>
                    <div className="person-main"><div className="avatar student-avatar"><Smile/></div><div className="person-info"><b>{student.full_name}</b>{student.additional_info && <small className="student-additional-info">{student.additional_info}</small>}</div></div>
                    <button type="button" className="icon-btn graph-person-action" title="Редактировать" onClick={() => openEdit(student)}><Pencil/></button>
                  </div>)}
                  {!students.length && <div className="empty-students">Нет назначенных учеников</div>}
                </div>}
              </section>;
              })}
            </div>
            {!activeTeachers.length && <div className="empty-state"><GraduationCap/><b>Пока нет учителей</b><span>Добавьте первого учителя, затем учеников и связи между ними.</span></div>}
            {!!unassignedStudents.length && <section className="unassigned"><h2 className="unassigned-title">Ученики без назначения</h2><div className="unassigned-grid">{unassignedStudents.map(student => <div className="person-card student-card unassigned-student-card" key={student.id}>
              <div className="person-main"><div className="avatar student-avatar"><Smile/></div><div className="person-info"><b>{student.full_name}</b>{student.additional_info && <small className="student-additional-info">{student.additional_info}</small>}</div></div>
              <div className="unassigned-student-actions">
                <button type="button" className="icon-btn graph-person-action" title="Редактировать" onClick={() => openEdit(student)}><Pencil/></button>
                <button className="btn small outline" disabled={!activeTeachers.length} onClick={() => { setStudentId(String(student.id)); setTeacherId(String(activeTeachers[0]?.id || "")); setModal({ mode: "assign" }); }}>Назначить</button>
              </div>
            </div>)}</div></section>}
          </section>
        </>}

        {page === "users" && <>
          <div className="toolbar user-toolbar">
            <div className="search"><Search/><input placeholder="Поиск по имени" value={search} onChange={e => setSearch(e.target.value)}/></div>
            <select className="user-sort" aria-label="Сортировка пользователей" value={userSort} onChange={e => setUserSort(e.target.value)}>
              <option value="name-asc">По имени</option><option value="name-desc">Имя: Я — А</option><option value="teachers">Сначала учителя</option><option value="students">Сначала ученики</option><option value="active">Сначала активные</option><option value="inactive">Сначала отключённые</option>
            </select>
            <span className="user-count">Количество пользователей: <b>{visibleUsers.length}</b></span>
            <button className="btn primary user-add-btn" onClick={() => openCreate()}><Plus/>Добавить пользователя</button>
          </div>
          <div className="user-list">{visibleUsers.map(user => <div className={"user-row" + (userInfo === user.id ? " is-info-open" : "")} key={user.id}>
            <div className={"avatar " + user.role}>{user.role === "teacher" ? <GraduationCap/> : user.role === "student" ? <Smile/> : <Users/>}</div>
            <b className="user-person-info">{user.full_name}</b>
            <div className="user-actions">
              {user.telegram_id
                ? <button className="user-action-btn connect-toggle disconnect" onClick={() => disconnectTelegram(user)} title="Отключить Telegram" aria-label="Отключить Telegram"><Unlink/><span>Отключить</span></button>
                : <button className="user-action-btn connect-toggle connect" disabled={!user.active} onClick={() => makeCode(user)} title={user.active ? "Создать код для подключения" : "Сначала активируйте участника"} aria-label="Подключить участника"><Link2/><span>Подключить</span></button>}
              <div className="user-info-wrap">
                <button
                  className={"user-action-btn user-info-btn" + (userInfo === user.id ? " is-open" : "")}
                  type="button"
                  title="Информация об участнике"
                  aria-label={"Информация об участнике: " + user.full_name}
                  aria-expanded={userInfo === user.id}
                  aria-controls={"user-info-" + user.id}
                  onClick={() => setUserInfo(current => current === user.id ? null : user.id)}
                ><Info/></button>
                {userInfo === user.id && <div className="user-info-popover" id={"user-info-" + user.id} role="status">
                  <div className="user-info-popover-head"><b>Информация</b><button type="button" onClick={() => setUserInfo(null)} aria-label="Закрыть"><X size={14}/></button></div>
                  <div className="user-info-line"><span className={"user-status-dot " + (user.active ? "is-active" : "is-inactive")}/><span>{user.active ? "Активен" : "Отключён"}</span></div>
                  <div className="user-info-line"><Link2 size={14}/><span>{user.telegram_id ? "Telegram подключён" : "Telegram не подключён"}</span></div>
                  <div className="user-info-login"><span>Telegram ID</span><b>{user.telegram_id || "Не подключён"}</b></div>
                  {["teacher", "student"].includes(user.role) && <div className="user-info-login"><span>Логин</span><b>{user.web_username || user.full_name}</b></div>}
                </div>}
              </div>
              <button className="user-action-btn edit-btn" onClick={() => openEdit(user)} title="Изменить профиль" aria-label="Изменить профиль"><Pencil/></button>
              <button className="user-action-btn danger-icon user-delete" onClick={() => removeUser(user)} title="Удалить пользователя" aria-label="Удалить пользователя"><Trash2/></button>
            </div>
          </div>)}</div>
        </>}

        {page === "chats" && <>
          <div className={"chat-layout" + (selectedChat ? " chat-layout-conversation-open" : " chat-layout-list-open")}><div className="chat-list">{profile?.role === "admin" && <div className="chat-filter-segment admin-chat-sections" role="group" aria-label="Раздел диалогов"><button type="button" className={chatSection === "participants" ? "active" : ""} onClick={() => { setChatSection("participants"); setSelectedChat(null); setMessages([]); }}>Чаты участников</button><button type="button" className={chatSection === "personal" ? "active" : ""} onClick={() => { setChatSection("personal"); setChatFilter("all"); setSelectedChat(null); setMessages([]); }}>Личные{personalChats.some(chat => Number(chat.unread_count) > 0) && <span className="unread-badge">{personalChats.reduce((sum, chat) => sum + (Number(chat.unread_count) || 0), 0) > 99 ? "99+" : personalChats.reduce((sum, chat) => sum + (Number(chat.unread_count) || 0), 0)}</span>}</button></div>}{profile?.role === "admin" && chatSection === "personal" && <button type="button" className="btn outline personal-chat-create" onClick={openCreatePersonalChat}><Plus size={15}/>Создать диалог</button>}{profile?.role !== "student" && <>
              <div className="chat-search-control">
                <Search size={17}/>
                <input aria-label="Поиск по имени" placeholder="Поиск по имени" value={chatSearch} onChange={e => setChatSearch(e.target.value)}/>
                {chatSearch && <button type="button" onClick={() => setChatSearch("")} aria-label="Очистить поиск"><X size={14}/></button>}
              </div>
              {(profile?.role === "teacher" || (profile?.role === "admin" && chatSection === "personal")) && <div className="chat-filter-segment" role="group" aria-label="Фильтр диалогов">
                <button type="button" className={chatFilter === "all" ? "active" : ""} aria-pressed={chatFilter === "all"} onClick={() => setChatFilter("all")}>
                  <MessageCircle size={14}/>{profile?.role === "admin" ? "Все личные" : "Все диалоги"}
                </button>
                <button type="button" className={chatFilter === "unread" ? "active" : ""} aria-pressed={chatFilter === "unread"} onClick={() => setChatFilter("unread")}>
                  <Check size={14}/>Непрочитанные
                </button>
              </div>}
            </>}
            <div className="chat-items-scroll">{visibleChats.map(chat => {
              const personal = chat.type === "personal";
              const showMessageCount = profile?.role === "admin" && chatSection === "participants" && !personal;
              const unreadCount = Number(chat.unread_count) || 0;
              const displayedCount = showMessageCount ? Number(chat.message_count) || 0 : unreadCount;
              return <button key={chat.id} className={"chat-item " + (selectedChat?.id === chat.id && (selectedChat?.type === "personal") === personal ? "selected " : "") + (unreadCount > 0 && !showMessageCount ? "has-unread" : "")} onClick={() => openChat(chat)}>
                <div className="chat-item-heading">
                  <div className={"chat-item-participants" + (profile?.role === "student" ? " is-student-view" : "")}>
                    {personal ? <span>{chat.title}</span> : <>{profile?.role === "admin" && <span>{chat.teacher.full_name}</span>}<span>{profile?.role === "student" ? chat.teacher.full_name : chat.student.full_name}</span>{profile?.role === "student" && <small>Учитель</small>}</>}
                    {personal && <small>Личный диалог</small>}
                  </div>
                  {(showMessageCount || unreadCount > 0) && <span className={showMessageCount ? "message-count-badge" : "unread-badge"} title={showMessageCount ? "Всего сообщений" : "Непрочитанные сообщения"} aria-label={showMessageCount ? displayedCount + " сообщений всего" : displayedCount + " непрочитанных сообщений"}>{displayedCount > 99 ? "99+" : displayedCount}</span>}
                </div>
              </button>;
            })}{!visibleChats.length && <div className="empty-state">{profile?.role === "admin" && chatSection === "personal" ? "Личных диалогов пока нет" : profile?.role === "student" ? "Пока нет активной переписки с учителем" : profile?.role === "admin" ? "Активных диалогов участников нет" : "По выбранному фильтру ничего не найдено"}</div>}</div></div>
            <div className="chat-detail">{selectedChat ? <>
              <div className="chat-head"><button type="button" className="mobile-chat-back" onClick={() => { setSelectedChat(null); setMessages([]); }} aria-label="Назад к списку диалогов"><ArrowLeft size={19}/><span>Диалоги</span></button><div className="chat-head-person"><b>{selectedChat.type === "personal" ? selectedChat.title : profile?.role === "student" ? selectedChat.teacher.full_name : selectedChat.student.full_name}</b>{selectedChat.type === "personal" && <small>Личный диалог · только UknowApp</small>}{selectedChat.type !== "personal" && profile?.role === "admin" && <small>{selectedChat.teacher.full_name}</small>}{selectedChat.type !== "personal" && profile?.role === "student" && <small>Ваш учитель</small>}</div><div className="chat-head-tools"><select aria-label="Фильтр сообщений" value={messageFilter} onChange={e => setMessageFilter(e.target.value)}><option value="all">Все сообщения</option><option value="media">Все вложения</option><option value="audio">Аудио</option><option value="photos">Фото</option><option value="files">Файлы и видео</option></select>{selectedChat.type !== "personal" && selectedChat.status !== "active" && <span className="role-tag">Закрыта</span>}</div></div>
              <div className="messages" ref={messagesViewportRef}>{visibleMessages.map(message => <MessageBubble message={message} key={message.id} onDelete={setDeleteMessageCandidate} viewerRole={profile?.role} />)}{!messages.length && <div className="empty-state">Сообщений пока нет</div>}{!!messages.length && !visibleMessages.length && <div className="empty-state">Нет сообщений этого типа</div>}</div>
              {(selectedChat.type === "personal" || selectedChat.status === "active") && <form className="chat-composer" onSubmit={sendChatMessage}>
                <textarea value={draft} onChange={e => setDraft(e.target.value)} onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); e.currentTarget.form?.requestSubmit(); } }} placeholder={selectedChat.type === "personal" ? "Личное сообщение…" : profile?.role === "admin" ? "Сообщение от администратора обеим сторонам…" : profile?.role === "student" ? "Сообщение учителю…" : "Ответить ученику…"} rows={2} maxLength={4000}/>
                <div className="composer-footer">
                  <div className="composer-tools">
                    {selectedChat.type !== "personal" && <label className="attach-control"><Paperclip size={16}/> Прикрепить файл<input type="file" accept="image/*,audio/*,video/*,.pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.txt,.zip" onChange={e => setAttachment(e.target.files?.[0] || null)}/></label>}
                    {attachment && <span className="selected-file">{attachment.name}<button type="button" onClick={() => setAttachment(null)} aria-label="Убрать файл"><X size={14}/></button></span>}
                  </div>
                  <button className="btn primary composer-send" disabled={!draft.trim() && !attachment}>Отправить <ChevronRight size={16}/></button>
                </div>
              </form>}
            </> : <div className="empty-state">{profile?.role === "student" ? "Ваша переписка с учителем появится здесь" : "Выберите ученика слева"}</div>}</div>
          </div>
        </>}
        {page === "additional" && profile?.role === "admin" && <section className="graph-panel additional-panel">
          <div className="additional-heading"><div><div className="eyebrow">ОБСЛУЖИВАНИЕ ДАННЫХ</div><h2>Дополнительно</h2></div><button type="button" className="btn outline" onClick={loadDataStats} disabled={dataBusy}><RefreshCw size={15}/>Обновить</button></div>
          <div className="data-stats-grid">
            <article className="data-stat-card">
              <span>База данных SQLite</span><b>{dataStats ? formatBytes(dataStats.database_bytes) : "—"}</b>
              <small>{dataStats?.users ?? "—"} пользователей · {dataStats?.active_users ?? "—"} активных</small>
              <div className="data-stat-details">
                <span>Учителя: <b>{dataStats?.teachers ?? "—"}</b></span><span>Ученики: <b>{dataStats?.students ?? "—"}</b></span>
                <span>Связи учитель–ученик: <b>{dataStats?.assignments ?? "—"}</b> ({dataStats?.active_assignments ?? "—"} активных)</span>
                <span>Диалоги: <b>{dataStats?.conversations ?? "—"}</b> ученических · <b>{dataStats?.personal_conversations ?? "—"}</b> личных</span>
                <span>Сообщения: <b>{dataStats?.total_messages ?? "—"}</b> всего</span>
                <span className="data-stat-subline">Ученические: {dataStats?.messages ?? "—"} · Личные: {dataStats?.personal_messages ?? "—"}</span>
                <span>Telegram-группы: <b>{dataStats?.telegram_groups ?? "—"}</b></span>
                <span>Коды подключения: <b>{dataStats?.connection_codes ?? "—"}</b></span>
              </div>
            </article>
            <article className="data-stat-card">
              <span>Файлы из диалогов, сохранённые на сервере</span><b>{dataStats ? formatBytes(dataStats.media_bytes) : "—"}</b>
              <small>{dataStats?.media_files ?? "—"} файлов · учитываются только реально существующие вложения</small>
              <div className="data-stat-details">
                <span>Изображения: <b>{dataStats?.media_images ?? "—"}</b></span>
                <span>Аудио и голосовые: <b>{dataStats?.media_audio ?? "—"}</b></span>
                <span>Видео: <b>{dataStats?.media_videos ?? "—"}</b></span>
                <span>Другие файлы: <b>{dataStats?.media_other ?? "—"}</b></span>
              </div>
            </article>
          </div>
          <div className="data-tools-grid">
            <article className="data-tool-card">
              <div className="data-tool-icon"><DatabaseIcon/></div><div><h3>База данных</h3><p>Полная резервная копия пользователей, назначений, переписок и настроек.</p></div>
              <div className="data-tool-actions"><button type="button" className="btn primary" onClick={() => downloadAdminFile("database")} disabled={dataBusy}>Скачать базу</button><label className="btn outline data-upload-label">{dataBusy ? "Загрузка…" : "Загрузить базу"}<input type="file" accept=".db,.sqlite,.sqlite3" disabled={dataBusy} onChange={e => { uploadAdminFile("database", e.target.files?.[0]); e.target.value = ""; }}/></label></div>
              <p className="data-warning">Восстановление заменит текущую базу целиком. Перед загрузкой сохраните текущую копию.</p>
            </article>
            <article className="data-tool-card">
              <div className="data-tool-icon"><ArchiveIcon/></div><div><h3>Архив переписок</h3><p>Сообщения личных и ученических диалогов вместе с сохранёнными вложениями. Архив можно восстановить на этой установке UknowApp.</p></div>
              <div className="data-tool-actions"><button type="button" className="btn primary" onClick={() => downloadAdminFile("dialogues")} disabled={dataBusy}>Скачать архив</button><label className="btn outline data-upload-label">{dataBusy ? "Загрузка…" : "Загрузить архив"}<input type="file" accept=".zip" disabled={dataBusy} onChange={e => { uploadAdminFile("dialogues", e.target.files?.[0]); e.target.value = ""; }}/></label></div>
              <p className="data-warning">Восстановление заменит историю сообщений в существующих диалогах. Сначала восстановите базу, если диалоги или участники были удалены.</p>
            </article>
          </div>
          <article className="data-cleanup-card">
            <div><div className="eyebrow">ХРАНЕНИЕ И ОЧИСТКА</div><h3>Удаление старых переписок и медиа</h3><p>Удаляются сообщения старше выбранного срока и связанные с ними архивные вложения. Аккаунты, назначения и сами диалоги сохраняются.</p></div>
            <div className="data-cleanup-actions"><label>Удалять старше<select value={retentionDays} onChange={e => setRetentionDays(e.target.value)} disabled={dataBusy}><option value="30">30 дней</option><option value="60">60 дней</option><option value="120">120 дней</option></select></label><button type="button" className="btn danger" onClick={cleanupOldDialogues} disabled={dataBusy}><Trash2 size={15}/>Удалить старые данные</button></div>
          </article>
        </section>}
      </div>
    </main>

    {modal && modal.mode !== "create-personal" && <div className="overlay" onMouseDown={() => setModal(null)}><section className={`modal${modal.mode === "create" ? " create-participant-modal" : ""}`} onMouseDown={e => e.stopPropagation()}>
      <div className="modal-head"><div><div className="eyebrow">{modal.mode === "create" ? "НОВЫЙ УЧАСТНИК" : modal.mode === "edit" ? "ПРОФИЛЬ УЧАСТНИКА" : "СВЯЗЬ УЧЕНИКА И УЧИТЕЛЯ"}</div><h2>{modal.mode === "create" ? "Добавить участника" : modal.mode === "edit" ? "Редактировать" : "Назначить ученика"}</h2></div><button className="icon-btn" onClick={() => setModal(null)}><X/></button></div>
      {modal.mode === "assign" ? <form className="stack" onSubmit={assign}>
        <label>Учитель<select value={teacherId} onChange={e => setTeacherId(e.target.value)} required>{activeTeachers.map(t => <option value={t.id} key={t.id}>{t.full_name}</option>)}</select></label>
        <label>Ученик<select value={studentId} onChange={e => setStudentId(e.target.value)} required>{activeStudents.map(s => <option value={s.id} key={s.id}>{s.full_name}</option>)}</select></label>
        <p className="hint">Если у ученика уже есть активное назначение, оно будет заменено новым.</p>
        <button className="btn primary" disabled={!activeStudents.length}>Создать связь</button>
      </form> : <form className="stack" onSubmit={saveUser}>
        <label>Имя и фамилия<input value={name} onChange={e => { const nextName = e.target.value; setName(nextName); if (!panelLogin || panelLogin === name) setPanelLogin(nextName); }} minLength="2" maxLength="160" required autoFocus/></label>
        {role === "student" && <label>Доп. инфо<input value={additionalInfo} onChange={e => setAdditionalInfo(e.target.value)} maxLength="500"/></label>}
        <label>Роль<select value={role} onChange={e => setRole(e.target.value)}><option value="teacher">Учитель</option><option value="student">Ученик</option></select></label>
        <label>Telegram ID <input type="text" inputMode="numeric" pattern="[0-9]*" value={telegramId} onChange={e => setTelegramId(e.target.value)} /></label>
        {["teacher", "student"].includes(role) && <>
          <div className="panel-credentials-panel">
            <div className="panel-credential-row panel-login-edit-row">
              <label htmlFor="panel-web-login">Логин веб-панели</label>
              <input id="panel-web-login" value={panelLogin || name} onChange={e => setPanelLogin(e.target.value)} minLength="2" maxLength="160" required autoComplete="off" />
            </div>
            {modal.mode === "edit" && users.find(u => u.id === modal.id)?.role === role && <div className="panel-credential-row panel-access-row">
              <span>Код доступа</span>
              <div className="panel-access-value"><b>XXXX-XXXX</b><button type="button" className="btn outline password-code-refresh" onClick={regeneratePanelAccessCode} disabled={savingUser} title="Старый код сразу перестанет действовать"><RefreshCw size={12}/>Обновить код</button></div>
            </div>}
          </div>
        </>}
        {modal.mode === "edit" && role !== users.find(u => u.id === modal.id)?.role && <p className="hint">При смене роли активные назначения будут закрыты. История переписок сохранится.</p>}
        <div className="modal-actions"><button className="btn primary" disabled={savingUser}>{savingUser ? "Сохраняем…" : <><Check/>Сохранить</>}</button>{modal.mode === "edit" && <button type="button" className="user-action-btn danger-icon user-delete" onClick={() => removeUser(users.find(u => u.id === modal.id))} disabled={savingUser} title="Удалить пользователя" aria-label="Удалить пользователя"><Trash2 size={16}/></button>}</div>
      </form>}
    </section></div>}

    {modal?.mode === "create-personal" && <div className="overlay" onMouseDown={() => setModal(null)}><section className="modal create-participant-modal" role="dialog" aria-modal="true" aria-labelledby="personal-chat-title" onMouseDown={e => e.stopPropagation()}>
      <div className="modal-head"><div><div className="eyebrow">ЛИЧНЫЕ СООБЩЕНИЯ</div><h2 id="personal-chat-title">Создать диалог</h2></div><button type="button" className="icon-btn" onClick={() => setModal(null)} aria-label="Закрыть"><X/></button></div>
      <form className="stack" onSubmit={event => {
        event.preventDefault();
        const value = event.currentTarget.elements.participant.value.trim().toLocaleLowerCase("ru");
        const selected = users.find(user => user.active && ["teacher", "student"].includes(user.role) && user.full_name.trim().toLocaleLowerCase("ru") === value);
        if (selected) void createPersonalChat(selected.id);
        else setError("Выберите участника из списка активных учителей и учеников");
      }}>
        <label>Участник<input name="participant" list="personal-participant-options" placeholder="Начните вводить имя" autoComplete="off" autoFocus required/></label>
        <datalist id="personal-participant-options">{users.filter(user => user.active && ["teacher", "student"].includes(user.role)).map(user => <option value={user.full_name} key={user.id}>{user.role === "teacher" ? "Учитель" : "Ученик"}</option>)}</datalist>
        <p className="hint">Начните вводить имя и выберите нужного участника. Личный диалог будет доступен только внутри UknowApp.</p>
        {error && <p className="form-error" role="alert">{error}</p>}
        <div className="modal-actions"><button type="button" className="btn ghost" onClick={() => setModal(null)}>Отмена</button><button type="submit" className="btn primary">Создать диалог</button></div>
      </form>
    </section></div>}
    {deleteCandidate && <div className="overlay" onMouseDown={() => !deletingUser && setDeleteCandidate(null)}>
      <section className="modal confirm-delete-modal" role="alertdialog" aria-modal="true" aria-labelledby="delete-user-title" onMouseDown={e => e.stopPropagation()}>
        <div className="modal-head">
          <div><div className="eyebrow">УДАЛЕНИЕ УЧАСТНИКА</div><h2 id="delete-user-title">Удалить участника?</h2></div>
          <button className="icon-btn" type="button" onClick={() => setDeleteCandidate(null)} disabled={deletingUser} aria-label="Закрыть"><X/></button>
        </div>
        <p className="hint">Профиль «<b>{deleteCandidate.full_name}</b>», связанные переписки и сообщения будут удалены. Это действие нельзя отменить.</p>
        <div className="modal-actions">
          <button type="button" className="btn ghost" onClick={() => setDeleteCandidate(null)} disabled={deletingUser}>Отмена</button>
          <button type="button" className="btn danger" onClick={confirmRemoveUser} disabled={deletingUser}>{deletingUser ? "Удаляем…" : <><Trash2/>Удалить участника</>}</button>
        </div>
      </section>
    </div>}
    {deleteMessageCandidate && <div className="overlay" onMouseDown={() => !deletingMessage && setDeleteMessageCandidate(null)}>
      <section className="modal confirm-delete-modal" role="alertdialog" aria-modal="true" aria-labelledby="delete-message-title" onMouseDown={e => e.stopPropagation()}>
        <div className="modal-head">
          <div><div className="eyebrow">УДАЛЕНИЕ СООБЩЕНИЯ</div><h2 id="delete-message-title">Удалить у всех?</h2></div>
          <button className="icon-btn" type="button" onClick={() => setDeleteMessageCandidate(null)} disabled={deletingMessage} aria-label="Закрыть"><X/></button>
        </div>
        <p className="hint">{selectedChat?.type === "personal" ? "Сообщение будет удалено из личного диалога UknowApp. Чужие сообщения удалить нельзя." : "Сообщение будет удалено из переписки UknowApp и предпринята попытка удалить его копии в Telegram у всех получателей. Чужие сообщения удалить нельзя."}</p>
        <div className="message-delete-preview">{deleteMessageCandidate.text || deleteMessageCandidate.metadata?.media?.file_name || "Вложение"}</div>
        <div className="modal-actions">
          <button type="button" className="btn ghost" onClick={() => setDeleteMessageCandidate(null)} disabled={deletingMessage}>Отмена</button>
          <button type="button" className="btn danger" onClick={confirmDeleteMessage} disabled={deletingMessage}>{deletingMessage ? "Удаляем…" : <><Trash2/>Удалить у всех</>}</button>
        </div>
      </section>
    </div>}
    {disconnectCandidate && <div className="overlay" onMouseDown={() => !disconnectingTelegram && setDisconnectCandidate(null)}>
      <section className="modal confirm-delete-modal" role="alertdialog" aria-modal="true" aria-labelledby="disconnect-telegram-title" onMouseDown={e => e.stopPropagation()}>
        <div className="modal-head">
          <div><div className="eyebrow">ОТКЛЮЧЕНИЕ TELEGRAM</div><h2 id="disconnect-telegram-title">Отключить Telegram?</h2></div>
          <button className="icon-btn" type="button" onClick={() => setDisconnectCandidate(null)} disabled={disconnectingTelegram} aria-label="Закрыть"><X/></button>
        </div>
        <p className="hint">Отключить Telegram у пользователя «<b>{disconnectCandidate.full_name}</b>»? Профиль и история переписки останутся в системе. Отправлять и получать сообщения через бота он не сможет до повторного подключения.</p>
        <div className="modal-actions">
          <button type="button" className="btn ghost" onClick={() => setDisconnectCandidate(null)} disabled={disconnectingTelegram}>Отмена</button>
          <button type="button" className="btn danger" onClick={confirmDisconnectTelegram} disabled={disconnectingTelegram}>{disconnectingTelegram ? "Отключаем…" : "Отключить Telegram"}</button>
        </div>
      </section>
    </div>}
    {issuedCredential && <div className="overlay" onMouseDown={() => setIssuedCredential(null)}><section className="modal credential-modal" onMouseDown={e => e.stopPropagation()}>
      <div className="modal-head"><div><div className="eyebrow">{issuedCredential.role === "student" ? "ЕДИНЫЙ КОД ДОСТУПА УЧЕНИКА" : "ЕДИНЫЙ КОД ДОСТУПА УЧИТЕЛЯ"}</div><h2>{issuedCredential.full_name}</h2></div><button className="icon-btn" onClick={() => setIssuedCredential(null)}><X/></button></div>
      <div className="credential-row"><span>Логин</span><b>{issuedCredential.username}</b><button type="button" className="icon-btn" onClick={async () => notify(await copyText(issuedCredential.username) ? "Логин скопирован" : "Не удалось скопировать логин")} aria-label="Скопировать логин"><Copy size={16}/></button></div>
      <div className="credential-password"><span>Код доступа</span><b>{issuedCredential.code}</b><button type="button" className="btn outline" onClick={async () => notify(await copyText(issuedCredential.code) ? "Код доступа скопирован" : "Не удалось скопировать код доступа")}><Copy/>Скопировать код</button></div>
      <p className="hint">Передайте {issuedCredential.role === "student" ? "ученику" : "учителю"} логин и этот код. Для входа в веб-панель он вводит логин + код, а для подключения Telegram отправляет только код боту. Новый код заменяет старый сразу в обоих местах.</p>
      <div className="modal-actions"><button type="button" className="btn ghost" onClick={() => setIssuedCredential(null)}>Закрыть</button><button type="button" className="btn primary" onClick={async () => notify(await copyText("Логин: " + issuedCredential.username + "\nКод доступа: " + issuedCredential.code) ? "Данные для входа скопированы" : "Не удалось скопировать данные")}><Copy/>Скопировать</button></div>
    </section></div>}
    {code && <div className="overlay" onMouseDown={() => setCode(null)}><section className="modal" onMouseDown={e => e.stopPropagation()}><div className="modal-head"><div><div className="eyebrow">ПОДКЛЮЧЕНИЕ TELEGRAM</div><h2>{code.full_name}</h2></div><button className="icon-btn" onClick={() => setCode(null)}><X/></button></div><div className="invite-code">{code.code}</div><p className="hint">{code.shared_access ? `Это единый код ${code.role === "student" ? "ученика" : "учителя"}: он подходит для входа в веб-панель вместе с логином и для подключения Telegram. Он действует, пока администратор не заменит его новым.` : "Передайте этот код ученику для подключения Telegram. Он действует до первого успешного подключения и используется один раз."}</p><div className="modal-actions"><button className="btn ghost" onClick={() => setCode(null)}>Закрыть</button><button className="btn primary" onClick={async () => notify(await copyText(code.code) ? "Код скопирован" : "Не удалось скопировать код")}><Copy/>Скопировать</button></div></section></div>}
    {toast && <div className="toast"><Check/>{toast}</div>}
  </div>;
}