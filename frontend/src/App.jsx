import { useCallback, useEffect, useMemo, useState } from "react";
import { Activity, Check, ChevronRight, GraduationCap, LogOut, MessageCircle, Pencil, Plus, RefreshCw, Search, ShieldCheck, Trash2, Users, X, Link2, Copy } from "lucide-react";

const API = import.meta.env.VITE_API_BASE_URL || "";
const ROLE = { teacher: "Учитель", student: "Ученик" };
const initialAuth = () => sessionStorage.getItem("uknowapp-auth") || "";

export default function App() {
  const [auth, setAuth] = useState(initialAuth);
  const [login, setLogin] = useState("admin");
  const [password, setPassword] = useState("");
  const [page, setPage] = useState("graph");
  const [users, setUsers] = useState([]);
  const [overview, setOverview] = useState(null);
  const [chats, setChats] = useState([]);
  const [selectedChat, setSelectedChat] = useState(null);
  const [messages, setMessages] = useState([]);
  const [search, setSearch] = useState("");
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
      const [people, summary, conversations] = await Promise.all([
        request("/api/admin/users"), request("/api/admin/overview"), request("/api/admin/conversations")
      ]);
      setUsers(people); setOverview(summary); setChats(conversations);
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  }, [auth, request]);

  useEffect(() => { refresh(); }, [refresh]);

  const notify = (message) => { setToast(message); window.setTimeout(() => setToast(""), 2600); };
  const activeTeachers = users.filter(u => u.active && u.role === "teacher");
  const activeStudents = users.filter(u => u.active && u.role === "student");
  const visibleUsers = useMemo(() => users.filter(u => (u.full_name + " " + (u.telegram_id || "")).toLowerCase().includes(search.toLowerCase())), [users, search]);
  const assignedStudentIds = new Set((overview?.teachers || []).flatMap(t => t.students.map(s => s.id)));
  const unassignedStudents = activeStudents.filter(student => !assignedStudentIds.has(student.id));

  async function signIn(event) {
    event.preventDefault(); setError("");
    try {
      const response = await fetch(API + "/api/auth/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ username: login, password }) });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || "Не удалось войти");
      const encoded = btoa(unescape(encodeURIComponent(login + ":" + password)));
      sessionStorage.setItem("uknowapp-auth", encoded); setAuth(encoded); setPassword("");
    } catch (e) { setError(e.message); }
  }

  function signOut() {
    sessionStorage.removeItem("uknowapp-auth"); setAuth(""); setUsers([]); setOverview(null); setChats([]); setMessages([]); setSelectedChat(null);
  }

  function openCreate(defaultRole = "teacher") {
    setModal({ mode: "create", id: null }); setName(""); setRole(defaultRole); setTelegramId("");
  }
  function openEdit(user) {
    setModal({ mode: "edit", id: user.id }); setName(user.full_name); setRole(user.role); setTelegramId(user.telegram_id ? String(user.telegram_id) : "");
  }

  async function saveUser(event) {
    event.preventDefault();
    const body = { full_name: name.trim(), role, telegram_id: telegramId.trim() ? Number(telegramId) : null };
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

  async function makeCode(user) {
    try {
      const result = await request("/api/admin/users/" + user.id + "/connection-code", { method: "POST" });
      setCode({ ...result, full_name: user.full_name }); 
    } catch (e) { setError(e.message); }
  }

  async function openChat(chat) {
    setSelectedChat(chat); setPage("chats");
    try { setMessages(await request("/api/admin/conversations/" + chat.id + "/messages")); }
    catch (e) { setError(e.message); }
  }

  if (!auth) return <div className="login-screen">
    <div className="login-card">
      <img src="/logo.svg" alt="UknowApp" className="login-logo" />
      <div className="eyebrow">ПАНЕЛЬ АДМИНИСТРАТОРА</div><h1>UknowApp</h1>
      <p className="muted">Управление учителями, учениками и переписками.</p>
      <form onSubmit={signIn} className="stack">
        <label>Логин<input value={login} onChange={e => setLogin(e.target.value)} autoComplete="username" /></label>
        <label>Пароль<input type="password" value={password} onChange={e => setPassword(e.target.value)} autoComplete="current-password" /></label>
        {error && <div className="alert">{error}</div>}
        <button className="btn primary" type="submit">Войти <ChevronRight size={17}/></button>
      </form>
    </div>
  </div>;

  return <div className="shell">
    <aside className="sidebar">
      <div className="brand"><img src="/logo.svg" alt="" /><span>Uknow<span>App</span></span></div>
      <div className="school-label">УПРАВЛЕНИЕ ШКОЛОЙ</div>
      <nav>
        <button className={page === "graph" ? "active" : ""} onClick={() => setPage("graph")}><Activity/>Структура</button>
        <button className={page === "users" ? "active" : ""} onClick={() => setPage("users")}><Users/>Пользователи</button>
        <button className={page === "chats" ? "active" : ""} onClick={() => setPage("chats")}><MessageCircle/>Переписки <i>{chats.length}</i></button>
      </nav>
      <div className="sidebar-bottom"><div className="secure"><ShieldCheck/><span>Локальная база данных<br/>Контакты скрыты ботом</span></div><button className="logout" onClick={signOut}><LogOut/>Выйти</button></div>
    </aside>

    <main className="main">
      <header className="topbar"><div><span>UknowApp</span><ChevronRight/><b>{({ graph: "Структура", users: "Пользователи", chats: "Переписки" })[page]}</b></div><button className="icon-btn" onClick={refresh} title="Обновить"><RefreshCw className={busy ? "spin" : ""}/></button></header>
      <div className="content">
        {error && <div className="alert alert-row">{error}<button onClick={() => setError("")}><X/></button></div>}
        {page === "graph" && <>
          <div className="page-title"><div><div className="eyebrow">ВИЗУАЛЬНОЕ УПРАВЛЕНИЕ</div><h1>Структура школы</h1><p>Добавляйте участников, меняйте их данные и назначайте учеников прямо на схеме.</p></div><button className="btn primary" onClick={() => openCreate()}><Plus/>Добавить участника</button></div>
          <div className="metrics">
            <div className="metric"><GraduationCap/><span>Учителя</span><b>{overview?.counts.teachers || 0}</b></div>
            <div className="metric"><Users/><span>Ученики</span><b>{overview?.counts.students || 0}</b></div>
            <div className="metric"><Link2/><span>Связи</span><b>{overview?.counts.assignments || 0}</b></div>
            <div className="metric"><MessageCircle/><span>Переписки</span><b>{overview?.counts.conversations || 0}</b></div>
          </div>
          <section className="graph-panel">
            <div className="section-head"><div><h2>Карта связей</h2><p>Действия доступны на карточках участников.</p></div><div className="legend"><span className="teacher-dot"/> Учителя <span className="student-dot"/> Ученики</div></div>
            <div className="root-node"><img src="/logo.svg" alt=""/><div><b>Администратор</b><small>Полное управление</small></div><span>ADMIN</span></div>
            <div className="tree-line"/>
            <div className="teacher-grid">
              {activeTeachers.map(teacher => <section className="teacher-branch" key={teacher.id}>
                <div className="person-card teacher-card">
                  <div className="person-main"><div className="avatar teacher-avatar"><GraduationCap/></div><div className="person-info"><b>{teacher.full_name}</b><small>Учитель · #{teacher.id}</small></div></div>
                  <div className="person-actions"><button title="Редактировать" onClick={() => openEdit(teacher)}><Pencil/></button><button className="danger-icon" title="Удалить" onClick={() => removeUser(teacher)}><Trash2/></button></div>
                </div>
                <div className="student-list">
                  {(overview?.teachers.find(t => t.id === teacher.id)?.students || []).map(student => <div className="person-card student-card" key={student.id}>
                    <div className="person-main"><div className="avatar student-avatar"><Users/></div><div className="person-info"><b>{student.full_name}</b><small>Ученик · #{student.id}</small></div></div>
                    <div className="person-actions"><button title="Редактировать" onClick={() => openEdit(student)}><Pencil/></button><button className="danger-icon" title="Удалить" onClick={() => removeUser(student)}><Trash2/></button></div>
                  </div>)}
                  {!(overview?.teachers.find(t => t.id === teacher.id)?.students || []).length && <div className="empty-students">Нет назначенных учеников</div>}
                </div>
                <button className="add-student" onClick={() => { setTeacherId(String(teacher.id)); setStudentId(activeStudents[0]?.id ? String(activeStudents[0].id) : ""); setModal({ mode: "assign" }); }}><Plus/>Назначить ученика</button>
              </section>)}
            </div>
            {!activeTeachers.length && <div className="empty-state"><GraduationCap/><b>Пока нет учителей</b><span>Добавьте первого учителя, затем учеников и связи между ними.</span><button className="btn primary" onClick={() => openCreate("teacher")}><Plus/>Добавить учителя</button></div>}
            {!!unassignedStudents.length && <section className="unassigned"><div className="section-head"><div><h2>Ученики без назначения</h2><p>Их можно назначить учителю прямо отсюда.</p></div></div><div className="unassigned-grid">{unassignedStudents.map(student => <div className="person-card student-card" key={student.id}><div className="person-main"><div className="avatar student-avatar"><Users/></div><div className="person-info"><b>{student.full_name}</b><small>Ученик · #{student.id}</small></div></div><div className="person-actions"><button title="Редактировать" onClick={() => openEdit(student)}><Pencil/></button><button className="danger-icon" title="Удалить" onClick={() => removeUser(student)}><Trash2/></button></div><button className="btn small outline" disabled={!activeTeachers.length} onClick={() => { setStudentId(String(student.id)); setTeacherId(String(activeTeachers[0]?.id || "")); setModal({ mode: "assign" }); }}>Назначить</button></div>)}</div></section>}
          </section>
        </>}

        {page === "users" && <>
          <div className="page-title"><div><div className="eyebrow">УЧЁТНЫЕ ЗАПИСИ</div><h1>Пользователи</h1><p>Создание, редактирование, смена ролей и удаление.</p></div><button className="btn primary" onClick={() => openCreate()}><Plus/>Добавить</button></div>
          <div className="toolbar"><div className="search"><Search/><input placeholder="Поиск по имени или Telegram ID" value={search} onChange={e => setSearch(e.target.value)}/></div><span>{visibleUsers.length} пользователей</span></div>
          <div className="user-list">{visibleUsers.map(user => <div className="user-row" key={user.id}>
            <div className={"avatar " + user.role}><Users/></div><div className="person-info"><b>{user.full_name}</b><small>#{user.id} · {user.telegram_id || "Telegram не подключён"} · {user.active ? "Активен" : "Отключён"}</small></div><span className={"role-tag " + user.role}>{ROLE[user.role]}</span>
            <button className="btn small" onClick={() => openEdit(user)}><Pencil/>Изменить</button><button className="icon-btn danger-icon" onClick={() => removeUser(user)} title="Удалить"><Trash2/></button>
            {user.active && !user.telegram_id && <button className="btn small outline" onClick={() => makeCode(user)}><Copy/>Код</button>}
          </div>)}</div>
        </>}

        {page === "chats" && <>
          <div className="page-title"><div><div className="eyebrow">ИСТОРИЯ ОБЩЕНИЯ</div><h1>Переписки</h1><p>Просмотр сообщений между учениками и учителями.</p></div></div>
          <div className="chat-layout"><div className="chat-list">{chats.map(chat => <button key={chat.id} className={"chat-item " + (selectedChat?.id === chat.id ? "selected" : "")} onClick={() => openChat(chat)}><b>{chat.student.full_name} ↔ {chat.teacher.full_name}</b><small>{chat.last_message}</small><span>{chat.status === "active" ? "Активна" : "Закрыта"}</span></button>)}{!chats.length && <div className="empty-state">Переписок пока нет</div>}</div>
            <div className="chat-detail">{selectedChat ? <><div className="chat-head"><b>{selectedChat.student.full_name} ↔ {selectedChat.teacher.full_name}</b><small>Переписка #{selectedChat.id}</small></div><div className="messages">{messages.map(message => <div className={"message " + message.sender_role} key={message.id}><b>{message.sender} <small>{ROLE[message.sender_role] || message.sender_role}</small></b><p>{message.text || "Вложение: " + message.content_type}</p></div>)}{!messages.length && <div className="empty-state">Сообщений пока нет</div>}</div></> : <div className="empty-state">Выберите переписку слева</div>}</div>
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
        <label>Telegram ID <input type="number" value={telegramId} onChange={e => setTelegramId(e.target.value)} placeholder="Не подключён"/></label>
        {modal.mode === "edit" && role !== users.find(u => u.id === modal.id)?.role && <p className="hint">При смене роли активные назначения будут закрыты. История переписок сохранится.</p>}
        <div className="modal-actions"><button type="button" className="btn ghost" onClick={() => setModal(null)}>Отмена</button><button className="btn primary"><Check/>Сохранить</button></div>
      </form>}
    </section></div>}

    {code && <div className="overlay" onMouseDown={() => setCode(null)}><section className="modal" onMouseDown={e => e.stopPropagation()}><div className="modal-head"><div><div className="eyebrow">ПОДКЛЮЧЕНИЕ TELEGRAM</div><h2>{code.full_name}</h2></div><button className="icon-btn" onClick={() => setCode(null)}><X/></button></div><div className="invite-code">{code.code}</div><p className="hint">Передайте этот код ученику/учителю для активации телеграмм-бота. Код действует 15 минут.</p><div className="modal-actions"><button className="btn ghost" onClick={() => setCode(null)}>Закрыть</button><button className="btn primary" onClick={() => navigator.clipboard.writeText(code.code).then(() => notify("Код скопирован"))}><Copy/>Скопировать</button></div></section></div>}
    {toast && <div className="toast"><Check/>{toast}</div>}
  </div>;
}
