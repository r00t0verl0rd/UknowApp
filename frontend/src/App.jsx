import { useCallback, useEffect, useMemo, useState } from "react";
import { Activity, Check, ChevronRight, GraduationCap, LogOut, MessageCircle, Pencil, Plus, RefreshCw, Search, Trash2, Users, X, Link2, Copy, Unlink, Paperclip, Moon, Sun } from "lucide-react";

const API = import.meta.env.VITE_API_BASE_URL || "";
const ROLE = { teacher: "Учитель", student: "Ученик", admin: "Администратор" };
const initialAuth = () => sessionStorage.getItem("uknowapp-auth") === "1" ? "1" : "";
const TIME_ZONES = (() => {
  try {
    const browserZone = Intl.DateTimeFormat().resolvedOptions().timeZone;
    const supported = typeof Intl.supportedValuesOf === "function" ? Intl.supportedValuesOf("timeZone") : [];
    return [...new Set(["UTC", browserZone, ...supported].filter(Boolean))]
      .sort((a, b) => a.localeCompare(b, "ru"));
  } catch {
    return ["UTC", "Europe/Amsterdam", "Europe/London", "Europe/Moscow", "Asia/Bangkok", "Asia/Tokyo", "America/New_York", "America/Los_Angeles"];
  }
})();

function formatTimeInZone(value, timeZone, options) {
  if (!value) return "";
  // SQLite may return UTC timestamps without an explicit offset. Treat those
  // values as UTC instead of letting the browser interpret them as local time.
  const normalized = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(value) ? value : value + "Z";
  const date = new Date(normalized);
  return Number.isNaN(date.getTime()) ? "" : date.toLocaleString("ru-RU", { ...options, timeZone });
}

function MessageBubble({ message, timeZone }) {
  const [mediaUrl, setMediaUrl] = useState("");
  const media = message.metadata?.media;
  useEffect(() => {
    if (!media || media.archive_status !== "stored") return undefined;
    let objectUrl = "";
    let cancelled = false;
    fetch(API + "/api/panel/messages/" + message.id + "/media", {
      credentials: "include"
    }).then(response => {
      if (!response.ok) throw new Error("media unavailable");
      return response.blob();
    }).then(blob => {
      if (cancelled) return;
      objectUrl = URL.createObjectURL(blob);
      setMediaUrl(objectUrl);
    }).catch(() => setMediaUrl(""));
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [message.id, media?.archive_status]);
  const kind = media?.kind || message.content_type;
  const label = media?.file_name || ({ voice: "Голосовое сообщение", video_note: "Видеокружочек", photo: "Фотография", video: "Видео", audio: "Аудио", document: "Документ", sticker: "Стикер", animation: "Анимация" }[kind] || "Вложение");
  return <div className={"message " + message.sender_role}>
    <b>{message.sender} <small>{ROLE[message.sender_role] || message.sender_role}</small></b>
    <time className="message-time">{formatTimeInZone(message.created_at, timeZone, { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })}</time>
    {message.text && <p>{message.text}</p>}
    {mediaUrl && kind === "photo" && <img className="chat-media-image" src={mediaUrl} alt={label} />}
    {mediaUrl && ["voice", "audio"].includes(kind) && <audio className="chat-media-player" controls preload="metadata" src={mediaUrl} />}
    {mediaUrl && ["video", "video_note", "animation"].includes(kind) && <video className="chat-media-video" controls playsInline preload="metadata" src={mediaUrl} />}
    {mediaUrl && !["photo", "voice", "audio", "video", "video_note", "animation"].includes(kind) && <a className="chat-media-download" href={mediaUrl} download={label}>Скачать: {label}</a>}
    {!mediaUrl && media && <small className="chat-media-status">{media.archive_status === "too_large_for_telegram_download" ? "Файл больше 20 МБ — Telegram Bot API не разрешил архивировать его" : media.archive_status === "download_failed" ? "Не удалось сохранить копию вложения" : "Загрузка вложения…"}</small>}
    {!media && !message.text && <p>Вложение: {message.content_type}</p>}
    {message.delivery_status && message.delivery_status !== "delivered" && <small className="message-delivery">{message.delivery_status === "partial" ? "Доставлено не всем участникам" : "Не доставлено в Telegram"}{message.metadata?.telegram_delivery_errors?.length ? " · " + message.metadata.telegram_delivery_errors.join("; ") : ""}</small>}
  </div>;
}

export default function App() {
  const [auth, setAuth] = useState(initialAuth);
  const [theme, setTheme] = useState(() => localStorage.getItem("uknowapp-theme") === "dark-soft" ? "dark-soft" : "light");
  const [timeZone, setTimeZone] = useState(() => {
    const saved = localStorage.getItem("uknowapp-timezone");
    if (saved && TIME_ZONES.includes(saved)) return saved;
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "Europe/Amsterdam";
  });
  const [profile, setProfile] = useState(null);
  const [teacherGraph, setTeacherGraph] = useState(null);
  const [draft, setDraft] = useState("");
  const [attachment, setAttachment] = useState(null);
  const [issuedCredential, setIssuedCredential] = useState(null);
  const [savingUser, setSavingUser] = useState(false);
  const [login, setLogin] = useState("admin");
  const [password, setPassword] = useState("");
  const [page, setPage] = useState("graph");
  const [users, setUsers] = useState([]);
  const [overview, setOverview] = useState(null);
  const [chats, setChats] = useState([]);
  const [selectedChat, setSelectedChat] = useState(null);
  const [messages, setMessages] = useState([]);
  const [search, setSearch] = useState("");
  const [chatSearch, setChatSearch] = useState("");
  const [chatFilter, setChatFilter] = useState("all");
  const [messageFilter, setMessageFilter] = useState("all");
  const [error, setError] = useState("");
  const [toast, setToast] = useState("");
  const [busy, setBusy] = useState(false);
  const [modal, setModal] = useState(null);
  const [name, setName] = useState("");
  const [teacherLogin, setTeacherLogin] = useState("");
  const [role, setRole] = useState("teacher");
  const [telegramId, setTelegramId] = useState("");
  const [teacherId, setTeacherId] = useState("");
  const [studentId, setStudentId] = useState("");
  const [code, setCode] = useState(null);

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
        sessionStorage.removeItem("uknowapp-auth");
        setAuth("");
        setProfile(null);
      }
    } finally { setBusy(false); }
  }, [auth, request]);

  useEffect(() => { refresh(); }, [refresh]);

  useEffect(() => {
    localStorage.setItem("uknowapp-theme", theme);
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  useEffect(() => {
    localStorage.setItem("uknowapp-timezone", timeZone);
  }, [timeZone]);

  useEffect(() => {
    if (!auth || page !== "chats") return undefined;
    let active = true;
    let inFlight = false;
    const interval = window.setInterval(async () => {
      if (inFlight) return;
      inFlight = true;
      try {
        const conversations = await request("/api/panel/conversations");
        if (!active) return;
        setChats(conversations);
        if (selectedChat?.id) {
          const rows = await request("/api/panel/conversations/" + selectedChat.id + "/messages");
          if (active) setMessages(rows);
        }
      } catch {
        // Keep the current conversation visible during brief network interruptions.
      } finally {
        inFlight = false;
      }
    }, 10000);
    return () => {
      active = false;
      window.clearInterval(interval);
    };
  }, [auth, page, selectedChat?.id, request]);

  const notify = (message) => { setToast(message); window.setTimeout(() => setToast(""), 2600); };
  const activeTeachers = users.filter(u => u.active && u.role === "teacher");
  const activeStudents = users.filter(u => u.active && u.role === "student");
  const visibleUsers = useMemo(() => users.filter(u => (u.full_name + " " + (u.telegram_id || "")).toLowerCase().includes(search.toLowerCase())), [users, search]);
  const assignedStudentIds = new Set((overview?.teachers || []).flatMap(t => t.students.map(s => s.id)));
  const unassignedStudents = activeStudents.filter(student => !assignedStudentIds.has(student.id));
  const visibleMessages = useMemo(() => messages.filter(message => {
    const kind = message.metadata?.media?.kind || message.content_type;
    if (messageFilter === "all") return true;
    if (messageFilter === "media") return kind !== "text" || Boolean(message.metadata?.media);
    if (messageFilter === "audio") return ["voice", "audio"].includes(kind);
    if (messageFilter === "photos") return kind === "photo";
    if (messageFilter === "files") return ["document", "video", "video_note", "animation"].includes(kind);
    return true;
  }), [messages, messageFilter]);
  const visibleChats = useMemo(() => {
    const query = chatSearch.trim().toLocaleLowerCase("ru");
    if (profile?.role === "admin") {
      return [...chats]
        .filter(chat => !query || chat.teacher.full_name.toLocaleLowerCase("ru").includes(query))
        .sort((a, b) =>
          a.teacher.full_name.localeCompare(b.teacher.full_name, "ru", { sensitivity: "base" }) ||
          a.student.full_name.localeCompare(b.student.full_name, "ru", { sensitivity: "base" })
        );
    }
    return chats.filter(chat => {
      const names = (chat.student.full_name + " " + chat.teacher.full_name).toLowerCase();
      const matchesSearch = !query || names.includes(query) || (chat.last_message || "").toLowerCase().includes(query);
      const matchesFilter = chatFilter === "all" || Number(chat.unread_count || 0) > 0;
      return matchesSearch && matchesFilter;
    });
  }, [chats, chatSearch, chatFilter, profile?.role]);

  function toggleTheme() {
    setTheme(current => current === "dark-soft" ? "light" : "dark-soft");
  }

  async function signIn(event) {
    event.preventDefault(); setError("");
    try {
      const response = await fetch(API + "/api/auth/login", { method: "POST", credentials: "include", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ username: login, password }) });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || "Не удалось войти");
      sessionStorage.setItem("uknowapp-auth", "1"); setProfile(result); setPage("graph"); setAuth("1"); setPassword("");
    } catch (e) { setError(e.message); }
  }

  async function signOut() {
    try {
      await fetch(API + "/api/auth/logout", { method: "POST", credentials: "include" });
    } catch {
      // Clear the local view even when the server is temporarily unreachable.
    }
    sessionStorage.removeItem("uknowapp-auth"); setAuth(""); setProfile(null); setTeacherGraph(null); setUsers([]); setOverview(null); setChats([]); setMessages([]); setSelectedChat(null); setDraft(""); setAttachment(null); setIssuedCredential(null);
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

  async function removeUser(user) {
    const ok = window.confirm("Удалить «" + user.full_name + "»? Связанные переписки и сообщения также будут удалены. Это действие нельзя отменить.");
    if (!ok) return;
    try {
      await request("/api/admin/users/" + user.id, { method: "DELETE" });
      if (selectedChat && (selectedChat.teacher.id === user.id || selectedChat.student.id === user.id)) { setSelectedChat(null); setMessages([]); }
      await refresh(); notify("Пользователь удалён");
    } catch (e) { setError(e.message); }
  }

  async function assign(event) {
    event.preventDefault();
    try {
      await request("/api/admin/assignments", { method: "POST", body: JSON.stringify({ teacher_id: Number(teacherId), student_id: Number(studentId) }) });
      setModal(null); await refresh(); notify("Ученик назначен учителю");
    } catch (e) { setError(e.message); }
  }

  async function disconnectTelegram(user) {
    const ok = window.confirm(
      "Отключить Telegram у «" + user.full_name + "»?\n\n" +
      "Пользователь и история переписки останутся в системе. " +
      "Отправлять и получать сообщения через бота он не сможет до повторного подключения."
    );
    if (!ok) return;
    try {
      await request("/api/admin/users/" + user.id + "/disconnect-telegram", { method: "POST" });
      await refresh();
      notify("Telegram отключён");
    } catch (e) { setError(e.message); }
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
      if (sentMessage?.delivery_status === "delivered") notify("Сообщение отправлено");
      else if (sentMessage?.delivery_status === "partial") notify("Сообщение доставлено не всем участникам");
      else notify("Сохранено в истории, но Telegram-доставка не удалась");
    } catch (e) { setError(e.message); }
  }

  if (!auth) return <div className="login-screen">
    <div className="login-card">
      <button type="button" className="theme-toggle login-theme-toggle" onClick={toggleTheme} title={theme === "dark-soft" ? "Светлая тема" : "Тёмная soft-тема"} aria-label={theme === "dark-soft" ? "Включить светлую тему" : "Включить тёмную soft-тему"}>
        {theme === "dark-soft" ? <Sun size={17}/> : <Moon size={17}/>}
      </button>
      <img src="/logo.png" alt="UknowApp" className="login-logo" />
      <div className="eyebrow">ЕДИНАЯ ПАНЕЛЬ ШКОЛЫ</div><h1>UknowApp</h1>
      <p className="muted">Вход администратора или учителя.</p>
      <form onSubmit={signIn} className="stack">
        <label>Логин администратора или учителя<input value={login} onChange={e => setLogin(e.target.value)} autoComplete="username" /></label>
        <label>Пароль администратора / код доступа учителя<input type="password" value={password} onChange={e => setPassword(e.target.value)} autoComplete="current-password" /></label>
        {error && <div className="alert">{error}</div>}
        <button className="btn primary" type="submit">Войти <ChevronRight size={17}/></button>
      </form>
    </div>
  </div>;

  return <div className="shell">
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
        <button className={page === "chats" ? "active" : ""} onClick={() => setPage("chats")}><MessageCircle/>Переписки <i>{chats.reduce((total, chat) => total + (Number(chat.unread_count) || 0), 0)}</i></button>
      </nav>
      <div className="sidebar-bottom"><button className="logout" onClick={signOut}><LogOut/>Выйти</button></div>
    </aside>

    <main className="main">
      <header className="topbar"><div><span>UknowApp</span><ChevronRight/><b>{profile?.role === "teacher" ? "Кабинет учителя" : ({ graph: "Структура", users: "Пользователи", chats: "Переписки" })[page]}</b><small className="topbar-user">{profile?.full_name}</small></div><div className="topbar-actions">
        <button type="button" className="theme-toggle" onClick={toggleTheme} title={theme === "dark-soft" ? "Светлая тема" : "Тёмная soft-тема"} aria-label={theme === "dark-soft" ? "Включить светлую тему" : "Включить тёмную soft-тему"}>
          {theme === "dark-soft" ? <Sun size={17}/> : <Moon size={17}/>}
        </button>
        <button className="icon-btn" onClick={refresh} title="Обновить"><RefreshCw className={busy ? "spin" : ""}/></button>
      </div></header>
      <div className="content">
        {error && <div className="alert alert-row">{error}<button onClick={() => setError("")}><X/></button></div>}
        {page === "graph" && profile?.role === "teacher" && <section className="teacher-readonly-graph">
          <div className="page-title"><div><div className="eyebrow">МОЯ ГРУППА</div><h1>Моя структура</h1><p>Здесь показаны только вы и ученики, назначенные вам администратором школы.</p></div></div>
          <div className="teacher-graph-root">
            <div className="teacher-graph-card">
              <div className="avatar teacher-avatar"><GraduationCap/></div>
              <div><b>{teacherGraph?.teacher.full_name || profile?.full_name}</b><small>Вы · Учитель</small></div>
              <span className="readonly-tag">Только просмотр</span>
            </div>
            <div className="teacher-graph-students">
              <div className="teacher-graph-connector"/>
              <div className="teacher-graph-student-grid">
                {(teacherGraph?.students || []).map(student => <div className="teacher-graph-card student" key={student.id}>
                  <div className="avatar student-avatar"><Users/></div>
                  <div><b>{student.full_name}</b><small>Ученик</small></div>
                </div>)}
              </div>
              {!(teacherGraph?.students || []).length && <div className="empty-state">Пока нет назначенных учеников</div>}
            </div>
          </div>
          <div className="teacher-graph-summary"><Users size={18}/><b>{teacherGraph?.counts.students || 0}</b><span>активных учеников в вашей группе</span></div>
        </section>}
        {page === "graph" && profile?.role === "admin" && <>
          <div className="page-title"><div><div className="eyebrow">ВИЗУАЛЬНОЕ УПРАВЛЕНИЕ</div><h1>Структура школы</h1><p>Добавляйте участников, меняйте их данные и назначайте учеников прямо на схеме.</p></div></div>
          <div className="metrics">
            <div className="metric"><GraduationCap/><span>Учителя</span><b>{overview?.counts.teachers || 0}</b></div>
            <div className="metric"><Users/><span>Ученики</span><b>{overview?.counts.students || 0}</b></div>
            <div className="metric"><Link2/><span>Связи</span><b>{overview?.counts.assignments || 0}</b></div>
            <div className="metric"><MessageCircle/><span>Переписки</span><b>{overview?.counts.conversations || 0}</b></div>
          </div>
          <section className="graph-panel">
            <div className="section-head"><div className="legend"><span className="teacher-dot"/> Учителя <span className="student-dot"/> Ученики</div></div>
            <div className="root-node"><img src="/logo.png" alt=""/><div><b>Администратор</b><small>Полное управление</small></div></div>
            <div className="teacher-grid">
              {activeTeachers.map(teacher => <section className="teacher-branch" key={teacher.id}>
                <div className="person-card teacher-card">
                  <div className="person-main"><div className="avatar teacher-avatar"><GraduationCap/></div><div className="person-info"><b>{teacher.full_name}</b><small>Учитель</small></div></div>
                  <div className="person-actions"><button title="Редактировать" onClick={() => openEdit(teacher)}><Pencil/></button><button className="danger-icon" title="Удалить" onClick={() => removeUser(teacher)}><Trash2/></button></div>
                </div>
                <div className="student-list">
                  {(overview?.teachers.find(t => t.id === teacher.id)?.students || []).map(student => <div className="person-card student-card" key={student.id}>
                    <div className="person-main"><div className="avatar student-avatar"><Users/></div><div className="person-info"><b>{student.full_name}</b><small>Ученик</small></div></div>
                    <div className="person-actions"><button title="Редактировать" onClick={() => openEdit(student)}><Pencil/></button><button className="danger-icon" title="Удалить" onClick={() => removeUser(student)}><Trash2/></button></div>
                  </div>)}
                  {!(overview?.teachers.find(t => t.id === teacher.id)?.students || []).length && <div className="empty-students">Нет назначенных учеников</div>}
                </div>
                <button className="add-student" onClick={() => { setTeacherId(String(teacher.id)); setStudentId(activeStudents[0]?.id ? String(activeStudents[0].id) : ""); setModal({ mode: "assign" }); }}><Plus/>Назначить ученика</button>
              </section>)}
            </div>
            {!activeTeachers.length && <div className="empty-state"><GraduationCap/><b>Пока нет учителей</b><span>Добавьте первого учителя, затем учеников и связи между ними.</span></div>}
            {!!unassignedStudents.length && <section className="unassigned"><div className="section-head"><div><h2>Ученики без назначения</h2><p>Их можно назначить учителю прямо отсюда.</p></div></div><div className="unassigned-grid">{unassignedStudents.map(student => <div className="person-card student-card" key={student.id}><div className="person-main"><div className="avatar student-avatar"><Users/></div><div className="person-info"><b>{student.full_name}</b><small>Ученик</small></div></div><div className="person-actions"><button title="Редактировать" onClick={() => openEdit(student)}><Pencil/></button><button className="danger-icon" title="Удалить" onClick={() => removeUser(student)}><Trash2/></button></div><button className="btn small outline" disabled={!activeTeachers.length} onClick={() => { setStudentId(String(student.id)); setTeacherId(String(activeTeachers[0]?.id || "")); setModal({ mode: "assign" }); }}>Назначить</button></div>)}</div></section>}
            <div className="graph-actions"><button className="btn primary" onClick={() => openCreate()}><Plus/>Добавить участника</button></div>
          </section>
        </>}

        {page === "users" && <>
          <div className="page-title"><div><div className="eyebrow">УЧЁТНЫЕ ЗАПИСИ</div><h1>Пользователи</h1><p>Создание, редактирование, смена ролей и удаление.</p></div><button className="btn primary" onClick={() => openCreate()}><Plus/>Добавить</button></div>
          <div className="toolbar"><div className="search"><Search/><input placeholder="Поиск по имени или Telegram ID" value={search} onChange={e => setSearch(e.target.value)}/></div><span>{visibleUsers.length} пользователей</span></div>
          <div className="user-list">{visibleUsers.map(user => <div className="user-row" key={user.id}>
            <div className={"avatar " + user.role}><Users/></div><div className="person-info"><b>{user.full_name}</b><small>#{user.id} · {user.telegram_id ? <span className="telegram-connected">Telegram ID {user.telegram_id}</span> : "Telegram не подключён"} · {user.role === "teacher" ? (user.has_access_code ? "Код доступа настроен" : "Код доступа не задан") + " · " : ""}{user.active ? "Активен" : "Отключён"}</small>{user.role === "teacher" && <small>Логин веб-панели: <b>{user.web_username || user.full_name}</b> · один код для веб-панели и Telegram</small>}</div><span className={"role-tag " + user.role}>{ROLE[user.role]}</span>
            <button className="btn small" onClick={() => openEdit(user)}><Pencil/>Изменить</button>{user.telegram_id && <button className="btn small disconnect" onClick={() => disconnectTelegram(user)} title="Отключить Telegram"><Unlink/>Отключить Telegram</button>}<button className="icon-btn danger-icon" onClick={() => removeUser(user)} title="Удалить"><Trash2/></button>
            {user.active && (user.role === "teacher" || !user.telegram_id) && <button className="btn small outline" onClick={() => makeCode(user)}><Copy/>{user.role === "teacher" ? "Новый код" : "Код"}</button>}
          </div>)}</div>
        </>}

        {page === "chats" && <>
          <div className="page-title"><div><div className="eyebrow">{profile?.role === "teacher" ? "МОИ УЧЕНИКИ" : "ИСТОРИЯ ОБЩЕНИЯ"}</div><h1>{profile?.role === "teacher" ? "Чаты с учениками" : "Переписки"}</h1><p>{profile?.role === "teacher" ? "Каждый ученик — отдельный диалог. Файлы и аудио находятся внутри нужной переписки." : "Наблюдение за переписками учеников и учителей. При необходимости администратор может подключиться к диалогу."}</p></div></div>
          <div className="chat-layout"><div className="chat-list"><div className="chat-list-tools">
              <div className="chat-search-control">
                <Search size={17}/>
                <input aria-label={profile?.role === "admin" ? "Найти учителя" : "Найти ученика"} placeholder={profile?.role === "admin" ? "Найти учителя" : "Найти ученика"} value={chatSearch} onChange={e => setChatSearch(e.target.value)}/>
                {chatSearch && <button type="button" onClick={() => setChatSearch("")} aria-label="Очистить поиск"><X size={14}/></button>}
              </div>
              {profile?.role === "admin" && <label className="timezone-control">
                <span>Часовой пояс</span>
                <select aria-label="Часовой пояс отображения времени" value={timeZone} onChange={e => setTimeZone(e.target.value)}>
                  {TIME_ZONES.map(zone => <option key={zone} value={zone}>{zone}</option>)}
                </select>
              </label>}
              {profile?.role !== "admin" && <div className="chat-filter-segment" role="group" aria-label="Фильтр диалогов">
                <button type="button" className={chatFilter === "all" ? "active" : ""} aria-pressed={chatFilter === "all"} onClick={() => setChatFilter("all")}>
                  <MessageCircle size={14}/>Все диалоги
                </button>
                <button type="button" className={chatFilter === "unread" ? "active" : ""} aria-pressed={chatFilter === "unread"} onClick={() => setChatFilter("unread")}>
                  <Check size={14}/>Непрочитанные
                </button>
              </div>}
              <div className="chat-list-caption">{profile?.role === "admin" ? "Сортировка по имени учителя" : visibleChats.length === chats.length ? "Все ваши диалоги" : "Показано " + visibleChats.length + " из " + chats.length}</div>
            </div>{visibleChats.map(chat => <button key={chat.id} className={"chat-item " + (selectedChat?.id === chat.id ? "selected" : "")} onClick={() => openChat(chat)}><b>{profile?.role === "teacher" ? chat.student.full_name : chat.teacher.full_name + " · " + chat.student.full_name}</b><small>{chat.last_message}</small><span>{chat.last_message_at ? formatTimeInZone(chat.last_message_at, timeZone, { hour: "2-digit", minute: "2-digit" }) + " · " : ""}{chat.unread_count ? chat.unread_count + " непрочитанных · " : ""}{chat.message_count} сообщений · {chat.status === "active" ? "Активна" : "Закрыта"}</span></button>)}{!chats.length && <div className="empty-state">Пока нет активных переписок</div>}{!!chats.length && !visibleChats.length && <div className="empty-state">{profile?.role === "admin" ? "Учитель не найден" : "По выбранному фильтру ничего не найдено"}</div>}</div>
            <div className="chat-detail">{selectedChat ? <>
              <div className="chat-head"><div><b>{selectedChat.student.full_name}</b><small>{profile?.role === "admin" ? "Учитель: " + selectedChat.teacher.full_name + " · " : ""}Переписка #{selectedChat.id}</small></div><div className="chat-head-tools"><select aria-label="Фильтр сообщений" value={messageFilter} onChange={e => setMessageFilter(e.target.value)}><option value="all">Все сообщения</option><option value="media">Все вложения</option><option value="audio">Аудио</option><option value="photos">Фото</option><option value="files">Файлы и видео</option></select><span className="role-tag">{selectedChat.status === "active" ? "Активна" : "Закрыта"}</span></div></div>
              <div className="messages">{visibleMessages.map(message => <MessageBubble message={message} timeZone={timeZone} key={message.id} />)}{!messages.length && <div className="empty-state">Сообщений пока нет</div>}{!!messages.length && !visibleMessages.length && <div className="empty-state">Нет сообщений этого типа</div>}</div>
              {selectedChat.status === "active" && <form className="chat-composer" onSubmit={sendChatMessage}>
                <textarea value={draft} onChange={e => setDraft(e.target.value)} placeholder={profile?.role === "admin" ? "Сообщение от администратора обеим сторонам…" : "Ответить ученику…"} rows={2} maxLength={4000}/>
                <div className="composer-footer">
                  <div className="composer-tools">
                    <label className="attach-control"><Paperclip size={16}/> Прикрепить файл<input type="file" accept="image/*,audio/*,video/*,.pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.txt,.zip" onChange={e => setAttachment(e.target.files?.[0] || null)}/></label>
                    {attachment && <span className="selected-file">{attachment.name}<button type="button" onClick={() => setAttachment(null)} aria-label="Убрать файл"><X size={14}/></button></span>}
                  </div>
                  <div className="composer-send"><small>{profile?.role === "admin" ? "Сообщение увидят ученик и учитель" : "Ответ сохранится в общем диалоге и отправится ученику в Telegram"}</small><button className="btn primary" disabled={!draft.trim() && !attachment}>Отправить <ChevronRight size={16}/></button></div>
                </div>
              </form>}
            </> : <div className="empty-state">Выберите ученика слева</div>}</div>
          </div>
        </>}
      </div>
      <footer>UknowApp <span>·</span> Локальная версия</footer>
    </main>

    {modal && <div className="overlay" onMouseDown={() => setModal(null)}><section className="modal" onMouseDown={e => e.stopPropagation()}>
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

    {issuedCredential && <div className="overlay" onMouseDown={() => setIssuedCredential(null)}><section className="modal credential-modal" onMouseDown={e => e.stopPropagation()}>
      <div className="modal-head"><div><div className="eyebrow">ЕДИНЫЙ КОД ДОСТУПА УЧИТЕЛЯ</div><h2>{issuedCredential.full_name}</h2></div><button className="icon-btn" onClick={() => setIssuedCredential(null)}><X/></button></div>
      <div className="credential-row"><span>Логин</span><b>{issuedCredential.username}</b><button type="button" className="icon-btn" onClick={() => navigator.clipboard.writeText(issuedCredential.username).then(() => notify("Логин скопирован"))} aria-label="Скопировать логин"><Copy size={16}/></button></div>
      <div className="credential-password"><span>Код доступа</span><b>{issuedCredential.code}</b></div>
      <p className="hint">Передайте учителю логин и этот код. Для веб-панели он вводит логин + код, а для подключения Telegram отправляет только код боту. Новый код заменяет старый сразу в обоих местах.</p>
      <div className="modal-actions"><button type="button" className="btn ghost" onClick={() => setIssuedCredential(null)}>Закрыть</button><button type="button" className="btn primary" onClick={() => navigator.clipboard.writeText("Логин: " + issuedCredential.username + "\nКод доступа: " + issuedCredential.code).then(() => notify("Данные для входа скопированы"))}><Copy/>Скопировать данные</button></div>
    </section></div>}
    {code && <div className="overlay" onMouseDown={() => setCode(null)}><section className="modal" onMouseDown={e => e.stopPropagation()}><div className="modal-head"><div><div className="eyebrow">ПОДКЛЮЧЕНИЕ TELEGRAM</div><h2>{code.full_name}</h2></div><button className="icon-btn" onClick={() => setCode(null)}><X/></button></div><div className="invite-code">{code.code}</div><p className="hint">{code.shared_access ? "Это единый код учителя: он подходит для входа в веб-панель вместе с логином и для подключения Telegram. Он действует, пока администратор не заменит его новым." : "Передайте этот код ученику для активации телеграмм-бота. Код действует 15 минут."}</p><div className="modal-actions"><button className="btn ghost" onClick={() => setCode(null)}>Закрыть</button><button className="btn primary" onClick={() => navigator.clipboard.writeText(code.code).then(() => notify("Код скопирован"))}><Copy/>Скопировать</button></div></section></div>}
    {toast && <div className="toast"><Check/>{toast}</div>}
  </div>;
}
