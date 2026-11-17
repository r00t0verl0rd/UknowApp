import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import Activity from "lucide-react/dist/esm/icons/activity.js";
import ArrowLeft from "lucide-react/dist/esm/icons/arrow-left.js";
import ArrowUpDown from "lucide-react/dist/esm/icons/arrow-up-down.js";
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
import MessageBubble from "./MessageBubble.jsx";

const API = import.meta.env.VITE_API_BASE_URL || "";
const initialAuth = () => localStorage.getItem("uknowapp-auth") === "1" || sessionStorage.getItem("uknowapp-auth") === "1" ? "1" : "";

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
  const [auth, setAuth] = useState(initialAuth);
  const [theme, setTheme] = useState(() => localStorage.getItem("uknowapp-theme-v2") || "dark-soft");
  const [profile, setProfile] = useState(null);
  const [teacherGraph, setTeacherGraph] = useState(null);
  const [draft, setDraft] = useState("");
  const [attachment, setAttachment] = useState(null);
  const [issuedCredential, setIssuedCredential] = useState(null);
  const [savingUser, setSavingUser] = useState(false);
  const [login, setLogin] = useState("");
  const [password, setPassword] = useState("");
  const [page, setPage] = useState("graph");
  const [users, setUsers] = useState([]);
  const [overview, setOverview] = useState(null);
  const [chats, setChats] = useState([]);
  const [selectedChat, setSelectedChat] = useState(null);
  const [messages, setMessages] = useState([]);
  const messagesViewportRef = useRef(null);
  const [search, setSearch] = useState("");
  const [userSort, setUserSort] = useState("students");
  const [userInfo, setUserInfo] = useState(null);
  const [chatSearch, setChatSearch] = useState("");
  const [chatFilter, setChatFilter] = useState("all");
  const [messageFilter, setMessageFilter] = useState("all");
  const [error, setError] = useState("");
  const [toast, setToast] = useState("");
  const [busy, setBusy] = useState(false);
  const [modal, setModal] = useState(null);

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
  const [deleteCandidate, setDeleteCandidate] = useState(null);
  const [deletingUser, setDeletingUser] = useState(false);
  const [deleteMessageCandidate, setDeleteMessageCandidate] = useState(null);
  const [deletingMessage, setDeletingMessage] = useState(false);
  const [disconnectCandidate, setDisconnectCandidate] = useState(null);
  const [disconnectingTelegram, setDisconnectingTelegram] = useState(false);
  const [name, setName] = useState("");
  const [teacherLogin, setTeacherLogin] = useState("");
  const [role, setRole] = useState("teacher");
  const [telegramId, setTelegramId] = useState("");
  const [teacherId, setTeacherId] = useState("");
  const [studentId, setStudentId] = useState("");
  const [code, setCode] = useState(null);

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
      const conversations = await request("/api/panel/conversations");
      setChats(conversations);
      if (who.role === "admin") {
        const [people, summary] = await Promise.all([
          request("/api/admin/users"), request("/api/admin/overview")
        ]);
        setUsers(people); setOverview(summary);
      } else {
        const graph = await request("/api/panel/graph");
        setTeacherGraph(graph);
        setUsers([]); setOverview(null);
      }
    } catch (e) {
      setError(e.message);
      if (String(e.message).toLowerCase().includes("учитель") || String(e.message).toLowerCase().includes("логин") || String(e.message).toLowerCase().includes("сессия") || String(e.message).toLowerCase().includes("войдите") || String(e.message).includes("401")) {
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

    const syncChats = async () => {
      if (!active) return;
      if (inFlight) {
        refreshPending = true;
        return;
      }
      inFlight = true;
      try {
        let rows = null;
        if (selectedChat?.id) {
          rows = await request("/api/panel/conversations/" + selectedChat.id + "/messages");
          if (!active) return;
          setMessages(rows);
        }
        // Loading messages marks them read for teachers. Fetch the list after
        // that write so unread counters are correct in the same refresh cycle.
        const conversations = await request("/api/panel/conversations");
        if (!active) return;
        setChats(conversations);
      } catch {
        // Keep the current conversation visible during brief network interruptions.
      } finally {
        inFlight = false;
        if (refreshPending && active) {
          refreshPending = false;
          void syncChats();
        }
      }
    };

    // One persistent SSE connection replaces the two-second HTTP polling loop.
    // The server sends an initial update event as soon as the stream is ready.
    const eventSource = new EventSource(API + "/api/panel/events", { withCredentials: true });
    eventSource.addEventListener("update", syncChats);

    const onVisibilityChange = () => {
      if (document.visibilityState === "visible") void syncChats();
    };
    document.addEventListener("visibilitychange", onVisibilityChange);

    return () => {
      active = false;
      eventSource.close();
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
  }, [auth, page, selectedChat?.id, request]);

  const notify = (message) => { setToast(message); window.setTimeout(() => setToast(""), 2600); };
  // Списки участников пересчитываются только при изменении массива пользователей.
  const activeTeachers = useMemo(() => users.filter(u => u.active && u.role === "teacher"), [users]);
  const activeStudents = useMemo(() => users.filter(u => u.active && u.role === "student"), [users]);
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
    // API отдаёт диалоги в порядке последней активности: сохраняем этот порядок
    // для всех ролей, чтобы самый недавно обновлённый диалог всегда был первым.
    if (profile?.role === "admin") {
      return chats.filter(chat =>
        !query || (chat.teacher.full_name + " " + chat.student.full_name).toLocaleLowerCase("ru").includes(query)
      );
    }
    return chats.filter(chat => {
      const names = (chat.student.full_name + " " + chat.teacher.full_name).toLowerCase();
      const matchesSearch = !query || names.toLocaleLowerCase("ru").includes(query);
      const matchesFilter = chatFilter === "all" || Number(chat.unread_count || 0) > 0;
      return matchesSearch && matchesFilter;
    });
  }, [chats, chatSearch, chatFilter, profile?.role]);

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
      localStorage.setItem("uknowapp-auth", "1"); sessionStorage.removeItem("uknowapp-auth"); setProfile(result); setPage("graph"); setAuth("1"); setPassword("");
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
    localStorage.removeItem("uknowapp-auth"); sessionStorage.removeItem("uknowapp-auth"); setAuth(""); setProfile(null); setTeacherGraph(null); setUsers([]); setOverview(null); setChats([]); setMessages([]); setSelectedChat(null); setDraft(""); setAttachment(null); setIssuedCredential(null);
  }

  function openCreate(defaultRole = "student") {
    setIssuedCredential(null); setModal({ mode: "create", id: null }); setName(""); setTeacherLogin(""); setRole(defaultRole); setTelegramId(""); setError("");
  }
  function openEdit(user) {
    setModal({ mode: "edit", id: user.id }); setName(user.full_name); setTeacherLogin(user.web_username || user.full_name); setRole(user.role); setTelegramId(user.telegram_id ? String(user.telegram_id) : ""); setError("");
  }

  async function saveUser(event) {
    event.preventDefault();
    setSavingUser(true);
    setError("");
    const body = { full_name: name.trim(), role, telegram_id: telegramId.trim() ? Number(telegramId) : null };
    if (role === "teacher") body.web_username = (teacherLogin || name).trim();
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
          code: saved.issued_access_code
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

  async function regenerateTeacherAccessCode() {
    if (!modal || modal.mode !== "edit" || role !== "teacher") return;
    setSavingUser(true);
    setError("");
    try {
      const issued = await request("/api/admin/users/" + modal.id + "/access-code", { method: "POST" });
      await refresh();
      setIssuedCredential({
        full_name: issued.full_name,
        username: issued.web_username || issued.full_name,
        code: issued.issued_access_code
      });
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
      setMessages(await request("/api/panel/conversations/" + chat.id + "/messages"));
      if (profile?.role === "teacher") setChats(await request("/api/panel/conversations"));
    }
    catch (e) { setError(e.message); }
  }

  async function confirmDeleteMessage() {
    const message = deleteMessageCandidate;
    if (!message || deletingMessage) return;
    setDeletingMessage(true);
    setError("");
    try {
      const result = await request("/api/panel/messages/" + message.id, { method: "DELETE" });
      setMessages(current => current.filter(item => item.id !== message.id));
      setDeleteMessageCandidate(null);
      if (selectedChat) setChats(await request("/api/panel/conversations"));
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
      if (attachment) {
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
      setMessages(await request("/api/panel/conversations/" + selectedChat.id + "/messages"));
      setChats(await request("/api/panel/conversations"));
      if (sentMessage?.delivery_status === "delivered") {
        if (profile?.role !== "teacher") notify("Сообщение отправлено");
      } else if (sentMessage?.delivery_status === "partial") {
        notify("Сообщение доставлено не всем участникам");
      } else {
        notify("Сохранено в истории, но Telegram-доставка не удалась");
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
      <div className="school-label">{profile?.role === "admin" ? "УПРАВЛЕНИЕ ШКОЛОЙ" : "РАБОЧЕЕ МЕСТО УЧИТЕЛЯ"}</div>
      <nav>
        <>
          <button className={page === "graph" ? "active" : ""} onClick={() => setPage("graph")}><Activity/>Структура</button>
          {profile?.role === "admin" && <>
          <button className={page === "users" ? "active" : ""} onClick={() => setPage("users")}><Users/>Пользователи</button>
          </>}
        </>
        <button className={page === "chats" ? "active" : ""} onClick={() => setPage("chats")}><MessageCircle/>Переписки</button>
      </nav>
      <div className="sidebar-bottom">
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
        <div className="topbar-context"><small className="topbar-user">{profile?.full_name}</small></div>
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
                  <div><b>{student.full_name}</b><small>Ученик</small></div>
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
                const students = overview?.teachers.find(t => t.id === teacher.id)?.students || [];
                return <section className="teacher-branch" key={teacher.id}>
                <div className="person-card teacher-card">
                  <div className="person-main"><div className="avatar teacher-avatar"><GraduationCap/></div><div className="person-info"><b>{teacher.full_name}</b><small>Учитель · {students.length} учен.</small></div></div>
                  <div className="person-actions"><button title="Редактировать" onClick={() => openEdit(teacher)}><Pencil/></button><button className="danger-icon" title="Удалить" onClick={() => removeUser(teacher)}><Trash2/></button></div>
                </div>
                <div className="student-list">
                  {students.map(student => <div className="person-card student-card" key={student.id}>
                    <div className="person-main"><div className="avatar student-avatar"><Smile/></div><div className="person-info"><b>{student.full_name}</b><small>Ученик</small></div></div>
                    <div className="person-actions"><button title="Редактировать" onClick={() => openEdit(student)}><Pencil/></button><button className="danger-icon" title="Удалить" onClick={() => removeUser(student)}><Trash2/></button></div>
                  </div>)}
                </div>
              </section>;
              })}       })}
                  >
                    <div className="person-main"><div className="avatar teacher-avatar"><GraduationCap/></div><div className="person-info"><b>{teacher.full_name}</b><small>Учитель · {students.length} учен.</small></div></div>
                    
                  </button>
                  <div className="person-actions"><button title="Редактировать" onClick={() => openEdit(teacher)}><Pencil/></button><button className="danger-icon" title="Удалить" onClick={() => removeUser(teacher)}><Trash2/></button></div>
                </div>
                <div className="student-list" id={"teacher-students-" + teacher.id} hidden={isCollapsed}>
                  {students.map(student => <div className="person-card student-card" key={student.id}>
                    <div className="person-main"><div className="avatar student-avatar"><Smile/></div><div className="person-info"><b>{student.full_name}</b><small>Ученик</small></div></div>
                    <div className="person-actions"><button title="Редактировать" onClick={() => openEdit(student)}><Pencil/></button><button className="danger-icon" title="Удалить" onClick={() => removeUser(student)}><Trash2/></button></div>
                  </div>)}
                  {!(overview?.teachers.find(t => t.id === teacher.id)?.students || []).length && <div className="empty-students">Нет назначенных учеников</div>}
                </div>
                <button className="add-student" onClick={() => { setTeacherId(String(teacher.id)); setStudentId(activeStudents[0]?.id ? String(activeStudents[0].id) : ""); setModal({ mode: "assign" }); }}><Plus/>Назначить ученика</button>
              </section>;
              })}

            </div>
            {!activeTeachers.length && <div className="empty-state"><GraduationCap/><b>Пока нет учителей</b><span>Добавьте первого учителя, затем учеников и связи между ними.</span></div>}
            {!!unassignedStudents.length && <section className="unassigned"><div className="section-head"><h2>Ученики без назначения</h2></div><div className="unassigned-grid">{unassignedStudents.map(student => <div className="person-card student-card unassigned-student-card" key={student.id}>
              <div className="person-main"><div className="avatar student-avatar"><Smile/></div><div className="person-info"><b>{student.full_name}</b><small>Ученик</small></div></div>
              <div className="unassigned-student-actions">
                <div className="person-actions"><button title="Редактировать" onClick={() => openEdit(student)}><Pencil/></button><button className="danger-icon" title="Удалить" onClick={() => removeUser(student)}><Trash2/></button></div>
                <button className="btn small outline" disabled={!activeTeachers.length} onClick={() => { setStudentId(String(student.id)); setTeacherId(String(activeTeachers[0]?.id || "")); setModal({ mode: "assign" }); }}>Назначить</button>
              </div>
            </div>)}</div></section>}
          </section>
        </>}

        {page === "users" && <>
          <div className="toolbar user-toolbar">
            <div className="search"><Search/><input placeholder="Поиск по имени или Telegram ID" value={search} onChange={e => setSearch(e.target.value)}/></div>
            <label className="user-sort"><ArrowUpDown size={15}/><select aria-label="Сортировка пользователей" value={userSort} onChange={e => setUserSort(e.target.value)}>
              <option value="name-asc">По имени</option><option value="name-desc">Имя: Я — А</option><option value="teachers">Сначала учителя</option><option value="students">Сначала ученики</option><option value="active">Сначала активные</option><option value="inactive">Сначала отключённые</option>
            </select></label>
            <span className="user-count">Количество пользователей: <b>{visibleUsers.length}</b></span>
            <button className="btn primary user-add-btn" onClick={() => openCreate()}><Plus/>Добавить пользователя</button>
          </div>
          <div className="user-list">{visibleUsers.map(user => <div className={"user-row" + (userInfo === user.id ? " is-info-open" : "")} key={user.id}>
            <div className={"avatar " + user.role}>{user.role === "teacher" ? <GraduationCap/> : user.role === "student" ? <Smile/> : <Users/>}</div>
            <div className="person-info user-person-info">
              <b>{user.full_name}</b>
            </div>
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
                  {user.role === "teacher" && <div className="user-info-login"><span>Логин</span><b>{user.web_username || user.full_name}</b></div>}
                </div>}
              </div>
              <button className="user-action-btn edit-btn" onClick={() => openEdit(user)} title="Изменить профиль" aria-label="Изменить профиль"><Pencil/></button>
              <button className="user-action-btn danger-icon user-delete" onClick={() => removeUser(user)} title="Удалить пользователя" aria-label="Удалить пользователя"><Trash2/></button>
            </div>
          </div>)}</div>
        </>}

        {page === "chats" && <>
          <div className={"chat-layout" + (selectedChat ? " chat-layout-conversation-open" : " chat-layout-list-open")}><div className="chat-list"><div className="chat-list-tools">
              <div className="chat-search-control">
                <Search size={17}/>
                <input aria-label="Поиск по имени" placeholder="Поиск по имени" value={chatSearch} onChange={e => setChatSearch(e.target.value)}/>
                {chatSearch && <button type="button" onClick={() => setChatSearch("")} aria-label="Очистить поиск"><X size={14}/></button>}
              </div>
              {profile?.role !== "admin" && <div className="chat-filter-segment" role="group" aria-label="Фильтр диалогов">
                <button type="button" className={chatFilter === "all" ? "active" : ""} aria-pressed={chatFilter === "all"} onClick={() => setChatFilter("all")}>
                  <MessageCircle size={14}/>Все диалоги
                </button>
                <button type="button" className={chatFilter === "unread" ? "active" : ""} aria-pressed={chatFilter === "unread"} onClick={() => setChatFilter("unread")}>
                  <Check size={14}/>Непрочитанные
                </button>
              </div>}
              
            </div><div className="chat-items-scroll">{visibleChats.map(chat => {
              const unreadCount = Number(chat.unread_count) || 0;
              return <button key={chat.id} className={"chat-item " + (selectedChat?.id === chat.id ? "selected " : "") + (unreadCount > 0 ? "has-unread" : "")} onClick={() => openChat(chat)}>
                <div className="chat-item-heading">
                  <div className="chat-item-participants">
                    {profile?.role === "admin" && <span>{chat.teacher.full_name}</span>}
                    <span>{chat.student.full_name}</span>
                  </div>
                  {profile?.role === "teacher" && unreadCount > 0 && <span className="unread-badge" title="Непрочитанные сообщения" aria-label={unreadCount + " непрочитанных сообщений"}>{unreadCount > 99 ? "99+" : unreadCount}</span>}
                </div>
                <span className="chat-item-meta">{chat.message_count} сообщений</span>
              </button>;
            })}{!chats.length && <div className="empty-state">Пока нет активных переписок</div>}{!!chats.length && !visibleChats.length && <div className="empty-state">{profile?.role === "admin" ? "Учитель не найден" : "По выбранному фильтру ничего не найдено"}</div>}</div></div>
            <div className="chat-detail">{selectedChat ? <>
              <div className="chat-head"><button type="button" className="mobile-chat-back" onClick={() => { setSelectedChat(null); setMessages([]); }} aria-label="Назад к списку диалогов"><ArrowLeft size={19}/><span>Диалоги</span></button><div className="chat-head-person"><b>{selectedChat.student.full_name}</b>{profile?.role === "admin" && <small>{selectedChat.teacher.full_name}</small>}</div><div className="chat-head-tools"><select aria-label="Фильтр сообщений" value={messageFilter} onChange={e => setMessageFilter(e.target.value)}><option value="all">Все сообщения</option><option value="media">Все вложения</option><option value="audio">Аудио</option><option value="photos">Фото</option><option value="files">Файлы и видео</option></select>{selectedChat.status !== "active" && <span className="role-tag">Закрыта</span>}</div></div>
              <div className="messages" ref={messagesViewportRef}>{visibleMessages.map(message => <MessageBubble message={message} key={message.id} onDelete={setDeleteMessageCandidate} viewerRole={profile?.role} />)}{!messages.length && <div className="empty-state">Сообщений пока нет</div>}{!!messages.length && !visibleMessages.length && <div className="empty-state">Нет сообщений этого типа</div>}</div>
              {selectedChat.status === "active" && <form className="chat-composer" onSubmit={sendChatMessage}>
                <textarea value={draft} onChange={e => setDraft(e.target.value)} onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); e.currentTarget.form?.requestSubmit(); } }} placeholder={profile?.role === "admin" ? "Сообщение от администратора обеим сторонам…" : "Ответить ученику…"} rows={2} maxLength={4000}/>
                <div className="composer-footer">
                  <div className="composer-tools">
                    <label className="attach-control"><Paperclip size={16}/> Прикрепить файл<input type="file" accept="image/*,audio/*,video/*,.pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.txt,.zip" onChange={e => setAttachment(e.target.files?.[0] || null)}/></label>
                    {attachment && <span className="selected-file">{attachment.name}<button type="button" onClick={() => setAttachment(null)} aria-label="Убрать файл"><X size={14}/></button></span>}
                  </div>
                  <div className="composer-send"><button className="btn primary" disabled={!draft.trim() && !attachment}>Отправить <ChevronRight size={16}/></button></div>
                </div>
              </form>}
            </> : <div className="empty-state">Выберите ученика слева</div>}</div>
          </div>
        </>}
      </div>
    </main>

    {modal && <div className="overlay" onMouseDown={() => setModal(null)}><section className={`modal${modal.mode === "create" ? " create-participant-modal" : ""}`} onMouseDown={e => e.stopPropagation()}>
      <div className="modal-head"><div><div className="eyebrow">{modal.mode === "create" ? "НОВЫЙ УЧАСТНИК" : modal.mode === "edit" ? "ПРОФИЛЬ УЧАСТНИКА" : "СВЯЗЬ УЧЕНИКА И УЧИТЕЛЯ"}</div><h2>{modal.mode === "create" ? "Добавить участника" : modal.mode === "edit" ? "Редактировать" : "Назначить ученика"}</h2></div><button className="icon-btn" onClick={() => setModal(null)}><X/></button></div>
      {modal.mode === "assign" ? <form className="stack" onSubmit={assign}>
        <label>Учитель<select value={teacherId} onChange={e => setTeacherId(e.target.value)} required>{activeTeachers.map(t => <option value={t.id} key={t.id}>{t.full_name}</option>)}</select></label>
        <label>Ученик<select value={studentId} onChange={e => setStudentId(e.target.value)} required>{activeStudents.map(s => <option value={s.id} key={s.id}>{s.full_name}</option>)}</select></label>
        <p className="hint">Если у ученика уже есть активное назначение, оно будет заменено новым.</p>
        <button className="btn primary" disabled={!activeStudents.length}>Создать связь</button>
      </form> : <form className="stack" onSubmit={saveUser}>
        <label>Имя и фамилия<input value={name} onChange={e => { const nextName = e.target.value; setName(nextName); if (!teacherLogin || teacherLogin === name) setTeacherLogin(nextName); }} minLength="2" maxLength="160" required autoFocus/></label>
        <label>Роль<select value={role} onChange={e => setRole(e.target.value)}><option value="teacher">Учитель</option><option value="student">Ученик</option></select></label>
        <label>Telegram ID <input type="text" inputMode="numeric" pattern="[0-9]*" value={telegramId} onChange={e => setTelegramId(e.target.value)} placeholder="Не подключён"/></label>
        {role === "teacher" && <>
          <label>Логин веб-панели<input value={teacherLogin || name} onChange={e => setTeacherLogin(e.target.value)} minLength="2" maxLength="160" required autoComplete="off" /></label>
          <p className="hint">По умолчанию логин совпадает с именем учителя. Для веб-панели используется этот логин и общий код доступа; в Telegram отправляется только код.</p>
          {modal.mode === "create" || users.find(u => u.id === modal.id)?.role !== "teacher"
            ? <div className="password-info"><RefreshCw size={16}/><span>При сохранении автоматически создадим единый код вида <b>XXXX-XXXX</b> для входа в веб-панель и подключения Telegram.</span></div>
            : <div className="password-actions">
                <div className="password-info"><RefreshCw size={16}/><span>Один и тот же код используется для веб-панели и Telegram. Новый код сразу заменит старый в обоих местах.</span></div>
                <button type="button" className="btn outline" onClick={regenerateTeacherAccessCode} disabled={savingUser}><RefreshCw size={15}/>Сгенерировать новый код</button>
              </div>}
        </>}
        {modal.mode === "edit" && role !== users.find(u => u.id === modal.id)?.role && <p className="hint">При смене роли активные назначения будут закрыты. История переписок сохранится.</p>}
        <div className="modal-actions"><button type="button" className="btn ghost" onClick={() => setModal(null)} disabled={savingUser}>Отмена</button><button className="btn primary" disabled={savingUser}>{savingUser ? "Сохраняем…" : <><Check/>Сохранить</>}</button></div>
      </form>}
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
        <p className="hint">Сообщение будет удалено из переписки UknowApp и предпринята попытка удалить его копии в Telegram у всех получателей. Чужие сообщения удалить нельзя.</p>
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
      <div className="modal-head"><div><div className="eyebrow">ЕДИНЫЙ КОД ДОСТУПА УЧИТЕЛЯ</div><h2>{issuedCredential.full_name}</h2></div><button className="icon-btn" onClick={() => setIssuedCredential(null)}><X/></button></div>
      <div className="credential-row"><span>Логин</span><b>{issuedCredential.username}</b><button type="button" className="icon-btn" onClick={async () => notify(await copyText(issuedCredential.username) ? "Логин скопирован" : "Не удалось скопировать логин")} aria-label="Скопировать логин"><Copy size={16}/></button></div>
      <div className="credential-password"><span>Код доступа</span><b>{issuedCredential.code}</b></div>
      <p className="hint">Передайте учителю логин и этот код. Для веб-панели он вводит логин + код, а для подключения Telegram отправляет только код боту. Новый код заменяет старый сразу в обоих местах.</p>
      <div className="modal-actions"><button type="button" className="btn ghost" onClick={() => setIssuedCredential(null)}>Закрыть</button><button type="button" className="btn primary" onClick={async () => notify(await copyText("Логин: " + issuedCredential.username + "\nКод доступа: " + issuedCredential.code) ? "Данные для входа скопированы" : "Не удалось скопировать данные")}><Copy/>Скопировать данные</button></div>
    </section></div>}
    {code && <div className="overlay" onMouseDown={() => setCode(null)}><section className="modal" onMouseDown={e => e.stopPropagation()}><div className="modal-head"><div><div className="eyebrow">ПОДКЛЮЧЕНИЕ TELEGRAM</div><h2>{code.full_name}</h2></div><button className="icon-btn" onClick={() => setCode(null)}><X/></button></div><div className="invite-code">{code.code}</div><p className="hint">{code.shared_access ? "Это единый код учителя: он подходит для входа в веб-панель вместе с логином и для подключения Telegram. Он действует, пока администратор не заменит его новым." : "Передайте этот код ученику для подключения Telegram. Он действует до первого успешного подключения и используется один раз."}</p><div className="modal-actions"><button className="btn ghost" onClick={() => setCode(null)}>Закрыть</button><button className="btn primary" onClick={async () => notify(await copyText(code.code) ? "Код скопирован" : "Не удалось скопировать код")}><Copy/>Скопировать</button></div></section></div>}
    {toast && <div className="toast"><Check/>{toast}</div>}
  </div>;
}
