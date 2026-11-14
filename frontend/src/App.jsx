import { useCallback, useEffect, useMemo, useState } from "react";
import { Activity, Check, ChevronRight, GraduationCap, LogOut, MessageCircle, Pencil, Plus, RefreshCw, Search, Trash2, Users, X, Link2, Copy, Unlink, Paperclip } from "lucide-react";

const API = import.meta.env.VITE_API_BASE_URL || "";
const ROLE = { teacher: "Учитель", student: "Ученик", admin: "Администратор" };
const initialAuth = () => sessionStorage.getItem("uknowapp-auth") || "";

function MessageBubble({ message, auth }) {
  const [mediaUrl, setMediaUrl] = useState("");
  const media = message.metadata?.media;
  useEffect(() => {
    if (!media || media.archive_status !== "stored") return undefined;
    let objectUrl = "";
    let cancelled = false;
    fetch(API + "/api/panel/messages/" + message.id + "/media", {
      headers: { Authorization: "Basic " + auth }
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
  }, [message.id, auth, media?.archive_status]);
  const kind = media?.kind || message.content_type;
  const label = media?.file_name || ({ voice: "Голосовое сообщение", video_note: "Видеокружочек", photo: "Фотография", video: "Видео", audio: "Аудио", document: "Документ", sticker: "Стикер", animation: "Анимация" }[kind] || "Вложение");
  return <div className={"message " + message.sender_role}>
    <b>{message.sender} <small>{ROLE[message.sender_role] || message.sender_role}</small></b>
    <time className="message-time">{message.created_at ? new Date(message.created_at).toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }) : ""}</time>
    {message.text && <p>{message.text}</p>}
    {mediaUrl && kind === "photo" && <img className="chat-media-image" src={mediaUrl} alt={label} />}
    {mediaUrl && ["voice", "audio"].includes(kind) && <audio className="chat-media-player" controls preload="metadata" src={mediaUrl} />}
    {mediaUrl && ["video", "video_note", "animation"].includes(kind) && <video className="chat-media-video" controls playsInline preload="metadata" src={mediaUrl} />}
    {mediaUrl && !["photo", "voice", "audio", "video", "video_note", "animation"].includes(kind) && <a className="chat-media-download" href={mediaUrl} download={label}>Скачать: {label}</a>}
    {!mediaUrl && media && <small className="chat-media-status">{media.archive_status === "too_large_for_telegram_download" ? "Файл больше 20 МБ — Telegram Bot API не разрешил архивировать его" : media.archive_status === "download_failed" ? "Не удалось сохранить копию вложения" : "Загрузка вложения…"}</small>}
    {!media && !message.text && <p>Вложение: {message.content_type}</p>}
  </div>;
}

export default function App() {
  const [auth, setAuth] = useState(initialAuth);
  const [profile, setProfile] = useState(null);
  const [teacherGraph, setTeacherGraph] = useState(null);
  const [draft, setDraft] = useState("");
  const [attachment, setAttachment] = useState(null);
  const [webPassword, setWebPassword] = useState("");
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
  const [role, setRole] = useState("teacher");
  const [telegramId, setTelegramId] = useState("");
  const [teacherId, setTeacherId] = useState("");
  const [studentId, setStudentId] = useState("");
  const [code, setCode] = useState(null);

  const request = useCallback(async (path, options = {}) => {
    const response = await fetch(API + path, {
      ...options,
      headers: { "Content-Type": "application/json", Authorization: "Basic " + auth, ...(options.headers || {}) }
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || "Ошибка запроса");
    return data;
  }, [auth]);

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
      if (String(e.message).toLowerCase().includes("учитель") || String(e.message).includes("401")) {
        sessionStorage.removeItem("uknowapp-auth");
        setAuth("");
        setProfile(null);
      }
    } finally { setBusy(false); }
  }, [auth, request]);

  useEffect(() => { refresh(); }, [refresh]);

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
  const visibleChats = useMemo(() => chats.filter(chat => {
    const names = (chat.student.full_name + " " + chat.teacher.full_name).toLowerCase();
    const matchesSearch = names.includes(chatSearch.toLowerCase()) || (chat.last_message || "").toLowerCase().includes(chatSearch.toLowerCase());
    const matchesFilter = chatFilter === "all" || Number(chat.unread_count || 0) > 0;
    return matchesSearch && matchesFilter;
  }), [chats, chatSearch, chatFilter]);

  async function signIn(event) {
    event.preventDefault(); setError("");
    try {
      const response = await fetch(API + "/api/auth/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ username: login, password }) });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || "Не удалось войти");
      const encoded = btoa(unescape(encodeURIComponent(login + ":" + password)));
      sessionStorage.setItem("uknowapp-auth", encoded); setProfile(result); setPage("graph"); setAuth(encoded); setPassword("");
    } catch (e) { setError(e.message); }
  }

  function signOut() {
    sessionStorage.removeItem("uknowapp-auth"); setAuth(""); setProfile(null); setTeacherGraph(null); setUsers([]); setOverview(null); setChats([]); setMessages([]); setSelectedChat(null); setDraft(""); setAttachment(null);
  }

  function openCreate(defaultRole = "teacher") {
    setModal({ mode: "create", id: null }); setName(""); setRole(defaultRole); setTelegramId(""); setWebPassword("");
  }
  function openEdit(user) {
    setModal({ mode: "edit", id: user.id }); setName(user.full_name); setRole(user.role); setTelegramId(user.telegram_id ? String(user.telegram_id) : ""); setWebPassword("");
  }

  async function saveUser(event) {
    event.preventDefault();
    const body = { full_name: name.trim(), role, telegram_id: telegramId.trim() ? Number(telegramId) : null };
    if (webPassword.trim()) body.web_password = webPassword.trim();
    try {
      if (modal.mode === "create") await request("/api/admin/users", { method: "POST", body: JSON.stringify(body) });
      else await request("/api/admin/users/" + modal.id, { method: "PATCH", body: JSON.stringify(body) });
      setModal(null); await refresh(); notify(modal.mode === "create" ? "Участник добавлен" : "Изменения сохранены");
    } catch (e) { setError(e.message); }
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
          headers: { Authorization: "Basic " + auth },
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
      const deliveryErrors = sentMessage?.metadata?.telegram_delivery_errors || [];
      if (sentMessage?.delivery_status === "delivered") notify("Сообщение отправлено");
      else if (sentMessage?.delivery_status === "partial") notify("Сообщение доставлено не всем участникам");
      else notify("Сохранено в истории, но Telegram-доставка не удалась");
    } catch (e) { setError(e.message); }
  }

  if (!auth) return <div className="login-screen">
    <div className="login-card">
      <img src="/logo.svg" alt="UknowApp" className="login-logo" />
      <div className="eyebrow">ЕДИНАЯ ПАНЕЛЬ ШКОЛЫ</div><h1>UknowApp</h1>
      <p className="muted">Вход администратора или учителя.</p>
      <form onSubmit={signIn} className="stack">
        <label>Логин администратора или ID учителя<input value={login} onChange={e => setLogin(e.target.value)} autoComplete="username" /></label>
        <label>Пароль<input type="password" value={password} onChange={e => setPassword(e.target.value)} autoComplete="current-password" /></label>
        {error && <div className="alert">{error}</div>}
        <button className="btn primary" type="submit">Войти <ChevronRight size={17}/></button>
      </form>
    </div>
  </div>;

  return <div className="shell">
    <aside className="sidebar">
      <div className="brand"><img src="/logo.svg" alt="" /><span>Uknow<span>App</span></span></div>
      <div className="school-label">{profile?.role === "admin" ? "УПРАВЛЕНИЕ ШКОЛОЙ" : "РАБОЧЕЕ МЕСТО УЧИТЕЛЯ"}</div>
      <nav>
        <>
          <button className={page === "graph" ? "active" : ""} onClick={() => setPage("graph")}><Activity/>Структура</button>
          {profile?.role === "admin" && <>
          <button className={page === "users" ? "active" : ""} onClick={() => setPage("users")}><Users/>Пользователи</button>
          </>}
        </>
        <button className={page === "chats" ? "active" : ""} onClick={() => setPage("chats")}><MessageCircle/>Переписки <i>{chats.length}</i></button>
      </nav>
      <div className="sidebar-bottom"><button className="logout" onClick={signOut}><LogOut/>Выйти</button></div>
    </aside>

    <main className="main">
      <header className="topbar"><div><span>UknowApp</span><ChevronRight/><b>{profile?.role === "teacher" ? "Кабинет учителя" : ({ graph: "Структура", users: "Пользователи", chats: "Переписки" })[page]}</b><small className="topbar-user">{profile?.full_name}</small></div><button className="icon-btn" onClick={refresh} title="Обновить"><RefreshCw className={busy ? "spin" : ""}/></button></header>
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
          <div className="page-title"><div><div className="eyebrow">ВИЗУАЛЬНОЕ УПРАВЛЕНИЕ</div><h1>Структура школы</h1><p>Добавляйте участников, меняйте их данные и назначайте учеников прямо на схеме.</p></div><button className="btn primary" onClick={() => openCreate()}><Plus/>Добавить участника</button></div>
          <div className="metrics">
            <div className="metric"><GraduationCap/><span>Учителя</span><b>{overview?.counts.teachers || 0}</b></div>
            <div className="metric"><Users/><span>Ученики</span><b>{overview?.counts.students || 0}</b></div>
            <div className="metric"><Link2/><span>Связи</span><b>{overview?.counts.assignments || 0}</b></div>
            <div className="metric"><MessageCircle/><span>Переписки</span><b>{overview?.counts.conversations || 0}</b></div>
          </div>
          <section className="graph-panel">
            <div className="section-head"><div><h2>Карта связей</h2><p>Действия доступны на карточках участников.</p></div><div className="legend"><span className="teacher-dot"/> Учителя <span className="student-dot"/> Ученики</div></div>
            <div className="root-node"><img src="/logo.svg" alt=""/><div><b>Администратор</b><small>Полное управление</small></div></div>
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
            {!activeTeachers.length && <div className="empty-state"><GraduationCap/><b>Пока нет учителей</b><span>Добавьте первого учителя, затем учеников и связи между ними.</span><button className="btn primary" onClick={() => openCreate("teacher")}><Plus/>Добавить учителя</button></div>}
            {!!unassignedStudents.length && <section className="unassigned"><div className="section-head"><div><h2>Ученики без назначения</h2><p>Их можно назначить учителю прямо отсюда.</p></div></div><div className="unassigned-grid">{unassignedStudents.map(student => <div className="person-card student-card" key={student.id}><div className="person-main"><div className="avatar student-avatar"><Users/></div><div className="person-info"><b>{student.full_name}</b><small>Ученик</small></div></div><div className="person-actions"><button title="Редактировать" onClick={() => openEdit(student)}><Pencil/></button><button className="danger-icon" title="Удалить" onClick={() => removeUser(student)}><Trash2/></button></div><button className="btn small outline" disabled={!activeTeachers.length} onClick={() => { setStudentId(String(student.id)); setTeacherId(String(activeTeachers[0]?.id || "")); setModal({ mode: "assign" }); }}>Назначить</button></div>)}</div></section>}
          </section>
        </>}

        {page === "users" && <>
          <div className="page-title"><div><div className="eyebrow">УЧЁТНЫЕ ЗАПИСИ</div><h1>Пользователи</h1><p>Создание, редактирование, смена ролей и удаление.</p></div><button className="btn primary" onClick={() => openCreate()}><Plus/>Добавить</button></div>
          <div className="toolbar"><div className="search"><Search/><input placeholder="Поиск по имени или Telegram ID" value={search} onChange={e => setSearch(e.target.value)}/></div><span>{visibleUsers.length} пользователей</span></div>
          <div className="user-list">{visibleUsers.map(user => <div className="user-row" key={user.id}>
            <div className={"avatar " + user.role}><Users/></div><div className="person-info"><b>{user.full_name}</b><small>#{user.id} · {user.telegram_id ? <span className="telegram-connected">Telegram ID {user.telegram_id}</span> : "Telegram не подключён"} · {user.role === "teacher" ? (user.has_web_password ? "Веб-доступ настроен" : "Пароль веб-панели не задан") + " · " : ""}{user.active ? "Активен" : "Отключён"}</small></div><span className={"role-tag " + user.role}>{ROLE[user.role]}</span>
            <button className="btn small" onClick={() => openEdit(user)}><Pencil/>Изменить</button>{user.telegram_id && <button className="btn small disconnect" onClick={() => disconnectTelegram(user)} title="Отключить Telegram"><Unlink/>Отключить Telegram</button>}<button className="icon-btn danger-icon" onClick={() => removeUser(user)} title="Удалить"><Trash2/></button>
            {user.active && !user.telegram_id && <button className="btn small outline" onClick={() => makeCode(user)}><Copy/>Код</button>}
          </div>)}</div>
        </>}

        {page === "chats" && <>
          <div className="page-title"><div><div className="eyebrow">{profile?.role === "teacher" ? "МОИ УЧЕНИКИ" : "ИСТОРИЯ ОБЩЕНИЯ"}</div><h1>{profile?.role === "teacher" ? "Чаты с учениками" : "Переписки"}</h1><p>{profile?.role === "teacher" ? "Каждый ученик — отдельный диалог. Файлы и аудио находятся внутри нужной переписки." : "Просмотр и участие в переписках учеников и учителей."}</p></div></div>
          <div className="chat-layout"><div className="chat-list"><div className="chat-list-tools"><input aria-label="Поиск по ученикам" placeholder="Найти ученика…" value={chatSearch} onChange={e => setChatSearch(e.target.value)}/><select aria-label="Фильтр переписок" value={chatFilter} onChange={e => setChatFilter(e.target.value)}><option value="all">Все диалоги</option><option value="unread">Есть непрочитанные</option></select></div>{visibleChats.map(chat => <button key={chat.id} className={"chat-item " + (selectedChat?.id === chat.id ? "selected" : "")} onClick={() => openChat(chat)}><b>{profile?.role === "teacher" ? chat.student.full_name : chat.student.full_name + " ↔ " + chat.teacher.full_name}</b><small>{chat.last_message}</small><span>{chat.unread_count ? chat.unread_count + " непрочитанных · " : ""}{chat.message_count} сообщений · {chat.status === "active" ? "Активна" : "Закрыта"}</span></button>)}{!chats.length && <div className="empty-state">Пока нет активных переписок</div>}{!!chats.length && !visibleChats.length && <div className="empty-state">По выбранному фильтру ничего не найдено</div>}</div>
            <div className="chat-detail">{selectedChat ? <>
              <div className="chat-head"><div><b>{selectedChat.student.full_name}</b><small>{profile?.role === "admin" ? "Учитель: " + selectedChat.teacher.full_name + " · " : ""}Переписка #{selectedChat.id}</small></div><div className="chat-head-tools"><select aria-label="Фильтр сообщений" value={messageFilter} onChange={e => setMessageFilter(e.target.value)}><option value="all">Все сообщения</option><option value="media">Все вложения</option><option value="audio">Аудио</option><option value="photos">Фото</option><option value="files">Файлы и видео</option></select><span className="role-tag">{selectedChat.status === "active" ? "Активна" : "Закрыта"}</span></div></div>
              <div className="messages">{visibleMessages.map(message => <MessageBubble message={message} auth={auth} key={message.id} />)}{!messages.length && <div className="empty-state">Сообщений пока нет</div>}{!!messages.length && !visibleMessages.length && <div className="empty-state">Нет сообщений этого типа</div>}</div>
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
        <label>Имя и фамилия<input value={name} onChange={e => setName(e.target.value)} minLength="2" maxLength="160" required autoFocus/></label>
        <label>Роль<select value={role} onChange={e => setRole(e.target.value)}><option value="teacher">Учитель</option><option value="student">Ученик</option></select></label>
        <label>Telegram ID <input type="text" inputMode="numeric" pattern="[0-9]*" value={telegramId} onChange={e => setTelegramId(e.target.value)} placeholder="Не подключён"/></label>
        {role === "teacher" && <><label>Пароль для веб-панели<input type="password" value={webPassword} onChange={e => setWebPassword(e.target.value)} minLength="8" maxLength="128" placeholder={modal.mode === "edit" ? "Оставьте пустым, чтобы не менять" : "Не менее 8 символов"} autoComplete="new-password"/></label><p className="hint">Учитель входит по внутреннему ID пользователя #{modal.id || "будет присвоен"} и этому паролю. Сам пароль в базе хранится в хешированном виде.</p></>}
        {modal.mode === "edit" && role !== users.find(u => u.id === modal.id)?.role && <p className="hint">При смене роли активные назначения будут закрыты. История переписок сохранится.</p>}
        <div className="modal-actions"><button type="button" className="btn ghost" onClick={() => setModal(null)}>Отмена</button><button className="btn primary"><Check/>Сохранить</button></div>
      </form>}
    </section></div>}

    {code && <div className="overlay" onMouseDown={() => setCode(null)}><section className="modal" onMouseDown={e => e.stopPropagation()}><div className="modal-head"><div><div className="eyebrow">ПОДКЛЮЧЕНИЕ TELEGRAM</div><h2>{code.full_name}</h2></div><button className="icon-btn" onClick={() => setCode(null)}><X/></button></div><div className="invite-code">{code.code}</div><p className="hint">Передайте этот код ученику/учителю для активации телеграмм-бота. Код действует 15 минут.</p><div className="modal-actions"><button className="btn ghost" onClick={() => setCode(null)}>Закрыть</button><button className="btn primary" onClick={() => navigator.clipboard.writeText(code.code).then(() => notify("Код скопирован"))}><Copy/>Скопировать</button></div></section></div>}
    {toast && <div className="toast"><Check/>{toast}</div>}
  </div>;
}
