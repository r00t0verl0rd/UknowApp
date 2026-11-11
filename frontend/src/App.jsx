import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity, ArrowDownLeft, ArrowUpRight, BookOpen, Check, ChevronRight, Copy,
  CircleHelp, Clock3, GraduationCap, KeyRound, LayoutDashboard, Link2, LockKeyhole, LogOut,
  MessageCircle, Plus, RefreshCw, Search, ShieldCheck, Users, X
} from "lucide-react";

const API = "http://127.0.0.1:8000";
const ROLE = { teacher: "Учитель", student: "Ученик", admin: "Администратор" };
const TYPE = {
  text: "Текст", photo: "Фото", video: "Видео", document: "Документ",
  voice: "Голосовое", audio: "Аудио", video_note: "Видеосообщение",
  sticker: "Стикер", animation: "GIF", contact: "Контакт", location: "Геопозиция",
  poll: "Опрос"
};

function basicHeader(value) {
  return value ? { Authorization: "Basic " + value } : {};
}

function App() {
  const [auth, setAuth] = useState(() => sessionStorage.getItem("uknowapp-auth") || "");
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [page, setPage] = useState("overview");
  const [overview, setOverview] = useState(null);
  const [users, setUsers] = useState([]);
  const [conversations, setConversations] = useState([]);
  const [selectedConversation, setSelectedConversation] = useState(null);
  const [messages, setMessages] = useState([]);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [toast, setToast] = useState("");
  const [editingUser, setEditingUser] = useState(null);
  const [editName, setEditName] = useState("");
  const [editTelegram, setEditTelegram] = useState("");
  const [connectionCode, setConnectionCode] = useState(null);
  const [generatingCodeUserId, setGeneratingCodeUserId] = useState(null);

  const request = useCallback(async (path, options = {}) => {
    const response = await fetch(API + path, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...basicHeader(auth),
        ...(options.headers || {})
      }
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || "Ошибка запроса");
    return data;
  }, [auth]);

  const refresh = useCallback(async () => {
    if (!auth) return;
    setLoading(true);
    setError("");
    try {
      const [summary, people, chats] = await Promise.all([
        request("/api/admin/overview"),
        request("/api/admin/users"),
        request("/api/admin/conversations")
      ]);
      setOverview(summary);
      setUsers(people);
      setConversations(chats);
    } catch (e) {
      setError(e.message);
      if (e.message.toLowerCase().includes("логин") || e.message.toLowerCase().includes("unauthorized")) {
        sessionStorage.removeItem("uknowapp-auth");
        setAuth("");
      }
    } finally {
      setLoading(false);
    }
  }, [auth, request]);

  useEffect(() => { refresh(); }, [refresh]);

  const showToast = (message) => {
    setToast(message);
    window.setTimeout(() => setToast(""), 2800);
  };

  async function login(event) {
    event.preventDefault();
    setError("");
    const encoded = btoa(unescape(encodeURIComponent(username + ":" + password)));
    try {
      const response = await fetch(API + "/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password })
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || "Не удалось войти");
      sessionStorage.setItem("uknowapp-auth", encoded);
      setAuth(encoded);
      setPassword("");
    } catch (e) { setError(e.message); }
  }

  function logout() {
    sessionStorage.removeItem("uknowapp-auth");
    setAuth("");
    setOverview(null);
    setUsers([]);
    setConversations([]);
    setMessages([]);
  }

  async function openConversation(item) {
    setSelectedConversation(item);
    setPage("conversations");
    try {
      const data = await request("/api/admin/conversations/" + item.id + "/messages");
      setMessages(data);
    } catch (e) { setError(e.message); }
  }

  async function addUser(event) {
    event.preventDefault();
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    try {
      await request("/api/admin/users", {
        method: "POST",
        body: JSON.stringify({
          full_name: form.get("full_name"),
          role: form.get("role"),
          telegram_id: form.get("telegram_id") ? Number(form.get("telegram_id")) : null
        })
      });
      formElement.reset();
      await refresh();
      showToast("Пользователь добавлен");
    } catch (e) { setError(e.message); }
  }

  async function assign(event) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
      await request("/api/admin/assignments", {
        method: "POST",
        body: JSON.stringify({
          teacher_id: Number(form.get("teacher_id")),
          student_id: Number(form.get("student_id"))
        })
      });
      await refresh();
      showToast("Ученик назначен учителю. Создана новая переписка.");
    } catch (e) { setError(e.message); }
  }

  async function toggleActive(user) {
    try {
      await request("/api/admin/users/" + user.id, {
        method: "PATCH",
        body: JSON.stringify({ active: !user.active })
      });
      await refresh();
      showToast(user.active ? "Пользователь отключён" : "Пользователь активирован");
    } catch (e) { setError(e.message); }
  }

  function beginEdit(user) {
    setEditingUser(user);
    setEditName(user.full_name);
    setEditTelegram(user.telegram_id ? String(user.telegram_id) : "");
  }

  async function saveUser(event) {
    event.preventDefault();
    try {
      await request("/api/admin/users/" + editingUser.id, {
        method: "PATCH",
        body: JSON.stringify({
          full_name: editName,
          telegram_id: editTelegram.trim() ? Number(editTelegram) : null
        })
      });
      setEditingUser(null);
      await refresh();
      showToast("Данные пользователя обновлены");
    } catch (e) { setError(e.message); }
  }

  async function generateConnectionCode(user) {
    setGeneratingCodeUserId(user.id);
    try {
      const result = await request("/api/admin/users/" + user.id + "/connection-code", {
        method: "POST"
      });
      setConnectionCode({ ...result, full_name: user.full_name });
      showToast("Одноразовый код создан");
    } catch (e) {
      setError(e.message);
    } finally {
      setGeneratingCodeUserId(null);
    }
  }

  async function copyConnectionCode() {
    if (!connectionCode) return;
    try {
      await navigator.clipboard.writeText(connectionCode.code);
      showToast("Код скопирован");
    } catch (e) {
      setError("Не удалось скопировать автоматически. Выделите код и скопируйте его вручную.");
    }
  }

  const filteredUsers = useMemo(() => users.filter((item) =>
    (item.full_name + " " + (item.telegram_id || "")).toLowerCase().includes(search.toLowerCase())
  ), [users, search]);

  if (!auth) {
    return (
      <div className="login-screen">
        <div className="login-art">
          <div className="login-orbit orbit-a" /><div className="login-orbit orbit-b" />
          <div className="login-brand-mark"><BookOpen size={28} /></div>
          <div className="login-copy">
            <div className="eyebrow">SCHOOL COMMUNICATION PLATFORM</div>
            <h1>Школа, где<br /><em>слышат каждого.</em></h1>
            <p>Единое безопасное пространство для общения учителей и учеников.</p>
            <div className="login-proof"><ShieldCheck size={16} /> Личные контакты остаются скрытыми</div>
          </div>
          <div className="login-foot">UKNOWAPP <span>·</span> LOCAL MVP</div>
        </div>
        <form className="login-form" onSubmit={login}>
          <div className="login-form-inner">
            <div className="mobile-brand"><BookOpen size={22} /> UknowApp</div>
            <div className="eyebrow">ПАНЕЛЬ УПРАВЛЕНИЯ</div>
            <h2>Добро пожаловать</h2>
            <p className="muted">Войдите, чтобы управлять структурой школы и переписками.</p>
            <label>Логин<input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" /></label>
            <label>Пароль<input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" /></label>
            {error && <div className="alert">{error}</div>}
            <button className="primary-btn full-btn" type="submit">Войти в систему <ChevronRight size={17} /></button>
            <div className="login-note"><LockKeyhole size={14} /> Доступ защищён локальной авторизацией</div>
          </div>
        </form>
      </div>
    );
  }

  const navItems = [
    { id: "overview", label: "Обзор", icon: LayoutDashboard },
    { id: "users", label: "Пользователи", icon: Users },
    { id: "conversations", label: "Переписки", icon: MessageCircle }
  ];

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand"><div className="brand-icon"><BookOpen size={21} /></div><span>uknow<span className="brand-light">app</span></span><div className="brand-dot" /></div>
        <div className="workspace-label">WORKSPACE</div>
        <div className="workspace"><div className="workspace-avatar">Ш</div><div><strong>Моя школа</strong><small>Локальная среда</small></div><span className="online-dot" /></div>
        <div className="nav-label">УПРАВЛЕНИЕ</div>
        <nav>
          {navItems.map((item) => {
            const Icon = item.icon;
            return <button key={item.id} className={"nav-item " + (page === item.id ? "active" : "")} onClick={() => setPage(item.id)}>
              <Icon size={18} /><span>{item.label}</span>
              {item.id === "conversations" && <span className="nav-count">{conversations.length}</span>}
            </button>;
          })}
        </nav>
        <div className="sidebar-bottom">
          <div className="security-card"><div className="security-icon"><ShieldCheck size={17} /></div><strong>Приватность включена</strong><p>Контакты участников скрыты при передаче сообщений.</p></div>
          <div className="profile-row"><div className="profile-avatar">А</div><div className="profile-info"><strong>Администратор</strong><small>Полный доступ</small></div><button className="icon-btn logout-btn" onClick={logout} title="Выйти"><LogOut size={17} /></button></div>
        </div>
      </aside>

      <main className="main-area">
        <header className="topbar">
          <div className="breadcrumb">UknowApp <ChevronRight size={14} /> <strong>{navItems.find((n) => n.id === page)?.label}</strong></div>
          <div className="topbar-actions"><span className="local-status"><span /> Локальный режим</span><button className="icon-btn" onClick={refresh} title="Обновить"><RefreshCw size={17} className={loading ? "spin" : ""} /></button><div className="top-avatar">А</div></div>
        </header>

        <div className="content-wrap">
          {error && <div className="alert page-alert"><span>{error}</span><button onClick={() => setError("")}><X size={15} /></button></div>}

          {page === "overview" && overview && (
            <>
              <div className="page-heading"><div><div className="eyebrow">СИСТЕМА УПРАВЛЕНИЯ ШКОЛОЙ</div><h1>Обзор <span className="heading-period">/</span> Иерархия</h1><p>Структура взаимодействия администрации, учителей и учеников.</p></div><button className="secondary-btn" onClick={() => setPage("users")}><Plus size={16} /> Добавить участника</button></div>
              <div className="stats-grid">
                <Stat icon={GraduationCap} label="Учителя" value={overview.counts.teachers} tone="violet" hint="Активные аккаунты" />
                <Stat icon={Users} label="Ученики" value={overview.counts.students} tone="blue" hint="В системе" />
                <Stat icon={Link2} label="Назначения" value={overview.counts.assignments} tone="mint" hint="Активные связи" />
                <Stat icon={MessageCircle} label="Сообщения" value={overview.counts.messages} tone="amber" hint="Всего сохранено" />
              </div>
              <section className="panel hierarchy-panel">
                <div className="panel-heading"><div><div className="eyebrow">ОРГАНИЗАЦИОННАЯ СТРУКТУРА</div><h2>Карта связей</h2><p>Нажмите на участника, чтобы перейти к его данным.</p></div><div className="graph-legend"><span><i className="legend-admin" /> Администрация</span><span><i className="legend-teacher" /> Учителя</span><span><i className="legend-student" /> Ученики</span></div></div>
                <div className="org-scroll">
                  <div className="org-chart">
                    <div className="org-root"><div className="node-icon admin-node"><ShieldCheck size={19} /></div><div><strong>Администратор</strong><small>Полное управление</small></div><span className="node-badge">ROOT</span></div>
                    <div className="root-connector" />
                    <div className="teacher-grid">
                      {overview.teachers.map((teacher) => <div className="teacher-branch" key={teacher.id}>
                        <div className="branch-line" />
                        <button className="org-node teacher-node" onClick={() => { setSearch(teacher.full_name); setPage("users"); }}>
                          <div className="node-icon teacher-icon"><GraduationCap size={19} /></div><div className="node-copy"><strong>{teacher.full_name}</strong><small>Учитель · ID {teacher.id}</small></div><span className="node-count">{teacher.students.length}</span>
                        </button>
                        <div className="student-connector" />
                        <div className="student-stack">
                          {teacher.students.map((student) => <button className="org-node student-node" key={student.id} onClick={() => { setSearch(student.full_name); setPage("users"); }}>
                            <div className="node-icon student-icon"><Users size={17} /></div><div className="node-copy"><strong>{student.full_name}</strong><small>Ученик · ID {student.id}</small></div><span className="node-state"><span /></span>
                          </button>)}
                          {!teacher.students.length && <div className="empty-students">Пока нет назначенных учеников</div>}
                        </div>
                      </div>)}
                      {!overview.teachers.length && <div className="empty-graph"><div className="empty-graph-icon"><Users size={24} /></div><strong>Пока нет участников</strong><p>Добавьте учителя и ученика, затем назначьте ученика учителю.</p><button className="primary-btn" onClick={() => setPage("users")}><Plus size={16} /> Добавить участников</button></div>}
                    </div>
                  </div>
                </div>
                <div className="graph-footer"><span><Activity size={15} /> Обновлено по данным базы SQLite</span><button className="text-btn" onClick={() => setPage("users")}>Управлять связями <ArrowUpRight size={15} /></button></div>
              </section>
              <div className="bottom-grid">
                <section className="panel mini-panel"><div className="mini-title"><div className="mini-icon blue-bg"><MessageCircle size={17} /></div><div><strong>Переписки</strong><small>Диалоги учителей и учеников</small></div><button className="text-btn" onClick={() => setPage("conversations")}>Все <ArrowUpRight size={14} /></button></div>
                  {conversations.slice(0, 3).map((chat) => <button className="recent-chat" key={chat.id} onClick={() => openConversation(chat)}><div className="chat-pair-avatar">{chat.student.full_name.slice(0, 1)}</div><div className="recent-chat-copy"><strong>{chat.student.full_name} <span>↔</span> {chat.teacher.full_name}</strong><small>{chat.last_message}</small></div><ChevronRight size={16} /></button>)}
                  {!conversations.length && <div className="small-empty">Назначьте ученика учителю, чтобы создать переписку.</div>}
                </section>
                <section className="panel mini-panel privacy-panel"><div className="mini-title"><div className="mini-icon green-bg"><ShieldCheck size={17} /></div><div><strong>Защита контактов</strong><small>Правила приватного общения</small></div></div><div className="privacy-line"><Check size={15} /><span>Сообщения пересылаются от имени бота</span></div><div className="privacy-line"><Check size={15} /><span>Телефоны, email и @username блокируются</span></div><div className="privacy-line"><Check size={15} /><span>История доступна администратору</span></div></section>
              </div>
            </>
          )}

          {page === "users" && (
            <>
              <div className="page-heading"><div><div className="eyebrow">УЧАСТНИКИ И СВЯЗИ</div><h1>Пользователи</h1><p>Создавайте аккаунты, подключайте Telegram и назначайте учеников учителям.</p></div><span className="soft-tag"><Users size={14} /> {users.length} аккаунтов</span></div>
              <div className="users-layout">
                <section className="panel users-panel"><div className="panel-heading compact"><div><h2>Все участники</h2><p>Управление доступом к школьной системе</p></div><div className="search-box"><Search size={16} /><input placeholder="Поиск по имени или ID" value={search} onChange={(e) => setSearch(e.target.value)} /></div></div>
                  <div className="table-wrap"><table><thead><tr><th>УЧАСТНИК</th><th>РОЛЬ</th><th>TELEGRAM ID</th><th>СТАТУС</th><th></th></tr></thead><tbody>
                    {filteredUsers.map((user) => <tr key={user.id}><td><div className="user-cell"><div className={"user-table-avatar " + user.role}>{user.full_name.slice(0, 1).toUpperCase()}</div><div><strong>{user.full_name}</strong><small>UID-{String(user.id).padStart(4, "0")}</small></div></div></td><td><span className={"role-pill " + user.role}>{ROLE[user.role]}</span></td><td className="id-cell">{user.telegram_id || <span className="not-linked">Не подключён</span>}</td><td><span className={"status-pill " + (user.active ? "active" : "inactive")}><i />{user.active ? "Активен" : "Отключён"}</span></td><td><div className="row-actions">{user.active && !user.telegram_id && <button className="text-btn code-action" disabled={generatingCodeUserId === user.id} onClick={() => generateConnectionCode(user)}><KeyRound size={13} />{generatingCodeUserId === user.id ? "Создаём…" : "Код подключения"}</button>}<button className="text-btn" onClick={() => beginEdit(user)}>Изменить</button><button className="text-btn" onClick={() => toggleActive(user)}>{user.active ? "Отключить" : "Включить"}</button></div></td></tr>)}
                  </tbody></table>{!filteredUsers.length && <div className="small-empty">Ничего не найдено.</div>}</div>
                  <div className="table-foot">Управление участниками доступно только администратору.</div>
                </section>
                <div className="forms-column">
                  <section className="panel form-panel"><div className="form-title"><div className="mini-icon violet-bg"><Plus size={17} /></div><div><h3>Новый участник</h3><p>Добавить учителя или ученика</p></div></div><form onSubmit={addUser}>
                    <label>Имя и фамилия<input name="full_name" required minLength="2" placeholder="Например, Анна Смирнова" /></label>
                    <label>Роль<select name="role"><option value="teacher">Учитель</option><option value="student">Ученик</option></select></label>
                    <label>Telegram ID <span className="optional">необязательно</span><input name="telegram_id" type="number" placeholder="Например, 123456789" /></label>
                    <div className="form-hint"><CircleHelp size={14} /> После добавления нажмите «Код подключения» в списке. Участник отправит код боту после команды /start.</div>
                    <button className="primary-btn full-btn" type="submit">Добавить участника <Plus size={16} /></button>
                  </form></section>
                  <section className="panel form-panel assign-panel"><div className="form-title"><div className="mini-icon mint-bg"><Link2 size={17} /></div><div><h3>Назначить ученика</h3><p>Создать приватную переписку</p></div></div><form onSubmit={assign}>
                    <label>Учитель<select name="teacher_id" required defaultValue=""><option value="" disabled>Выберите учителя</option>{users.filter((u) => u.role === "teacher" && u.active).map((u) => <option key={u.id} value={u.id}>{u.full_name}</option>)}</select></label>
                    <label>Ученик<select name="student_id" required defaultValue=""><option value="" disabled>Выберите ученика</option>{users.filter((u) => u.role === "student" && u.active).map((u) => <option key={u.id} value={u.id}>{u.full_name}</option>)}</select></label>
                    <div className="form-hint"><Link2 size={14} /> При переназначении история старого диалога сохраняется.</div>
                    <button className="primary-btn full-btn mint-btn" type="submit">Создать назначение <ChevronRight size={16} /></button>
                  </form></section>
                </div>
              </div>
            </>
          )}

          {page === "conversations" && (
            <>
              <div className="page-heading"><div><div className="eyebrow">ПЕРЕПИСКИ И ИСТОРИЯ</div><h1>Диалоги</h1><p>Просмотр сообщений между учениками и учителями через Telegram-бота.</p></div><span className="soft-tag"><LockKeyhole size={14} /> Только администратор</span></div>
              <div className="chat-layout panel">
                <div className="chat-list"><div className="chat-list-header"><strong>Все переписки</strong><span>{conversations.length}</span></div>
                  {conversations.map((chat) => <button key={chat.id} className={"chat-list-item " + (selectedConversation?.id === chat.id ? "selected" : "")} onClick={() => openConversation(chat)}>
                    <div className="chat-pair-avatar">{chat.student.full_name.slice(0, 1)}</div><div className="chat-list-copy"><strong>{chat.student.full_name}</strong><small>{chat.teacher.full_name}</small><p>{chat.last_message}</p></div><ChevronRight size={15} />
                  </button>)}
                  {!conversations.length && <div className="small-empty">Пока нет переписок. Создайте назначение в разделе «Пользователи».</div>}
                </div>
                <div className="chat-detail">
                  {selectedConversation ? <><div className="chat-detail-head"><div className="chat-pair-avatar large">{selectedConversation.student.full_name.slice(0, 1)}</div><div><strong>{selectedConversation.student.full_name} <span>↔</span> {selectedConversation.teacher.full_name}</strong><small>Диалог #{selectedConversation.id} · {selectedConversation.status === "active" ? "Активен" : "Закрыт"}</small></div><span className="secure-label"><LockKeyhole size={13} /> Приватный чат</span></div>
                    <div className="messages-area">{messages.map((message) => <div className={"message-row " + message.sender_role} key={message.id}><div className="message-avatar">{message.sender.slice(0, 1)}</div><div className="message-bubble"><div className="message-meta"><strong>{message.sender}</strong><span>{ROLE[message.sender_role] || message.sender_role}</span></div>{message.delivery_status === "blocked_contact" ? <div className="blocked-message"><ShieldCheck size={15} /> Контактные данные скрыты системой</div> : <><div className="message-text">{message.text || ("Вложение: " + (TYPE[message.content_type] || message.content_type))}</div>{message.content_type !== "text" && <div className="attachment-tag"><ArrowDownLeft size={13} /> {TYPE[message.content_type] || message.content_type}</div>}</>}<div className="message-time">{new Date(message.created_at).toLocaleString("ru-RU")} · {message.delivery_status === "delivered" ? "Доставлено" : message.delivery_status}</div></div></div>)}
                      {!messages.length && <div className="messages-empty"><MessageCircle size={24} /><strong>Сообщений пока нет</strong><span>История появится здесь после первого сообщения.</span></div>}
                    </div><div className="chat-readonly"><LockKeyhole size={14} /> Режим просмотра — отправка сообщений из админ-панели отключена.</div>
                  </> : <div className="messages-empty"><MessageCircle size={28} /><strong>Выберите переписку</strong><span>История диалога отобразится в этой области.</span></div>}
                </div>
              </div>
            </>
          )}
          <footer className="app-footer"><span>UKNOWAPP <b>0.1 MVP</b></span><span>Локальная база данных · SQLite</span></footer>
        </div>
      </main>
      {connectionCode && <div className="modal-backdrop" onMouseDown={() => setConnectionCode(null)}>
        <section className="edit-modal connection-modal" onMouseDown={(event) => event.stopPropagation()}>
          <div className="modal-heading">
            <div><div className="eyebrow">ПРИВЯЗКА TELEGRAM</div><h2>Код подключения готов</h2></div>
            <button className="icon-btn" onClick={() => setConnectionCode(null)}><X size={18} /></button>
          </div>
          <p className="modal-description">{connectionCode.full_name} · {ROLE[connectionCode.role]}</p>
          <div className="invite-code">{connectionCode.code}</div>
          <div className="code-expiry"><Clock3 size={14} /> Действует 15 минут · до {new Date(connectionCode.expires_at).toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" })}</div>
          <div className="connection-steps">
            <strong>Передай этот код участнику:</strong>
            <span>1. Открыть твоего Telegram-бота и отправить /start.</span>
            <span>2. Отправить код отдельным сообщением.</span>
            <span>3. После успешной привязки бот подтвердит подключение.</span>
          </div>
          <div className="modal-actions">
            <button type="button" className="secondary-btn" onClick={() => setConnectionCode(null)}>Закрыть</button>
            <button type="button" className="primary-btn" onClick={copyConnectionCode}><Copy size={15} /> Скопировать код</button>
          </div>
          <p className="code-security-note"><LockKeyhole size={13} /> Код одноразовый. После использования его нельзя применить повторно.</p>
        </section>
      </div>}
      {editingUser && <div className="modal-backdrop" onMouseDown={() => setEditingUser(null)}>
        <section className="edit-modal" onMouseDown={(event) => event.stopPropagation()}>
          <div className="modal-heading"><div><div className="eyebrow">УПРАВЛЕНИЕ УЧАСТНИКОМ</div><h2>Редактировать профиль</h2></div><button className="icon-btn" onClick={() => setEditingUser(null)}><X size={18} /></button></div>
          <p className="modal-description">{ROLE[editingUser.role]} · UID-{String(editingUser.id).padStart(4, "0")}</p>
          <form onSubmit={saveUser} className="modal-form">
            <label>Имя и фамилия<input value={editName} onChange={(event) => setEditName(event.target.value)} required minLength="2" /></label>
            <label>Telegram ID<input type="number" value={editTelegram} onChange={(event) => setEditTelegram(event.target.value)} placeholder="Не подключён" /></label>
            <div className="form-hint"><CircleHelp size={14} /> Участник должен запустить бота командой /start после привязки ID.</div>
            <div className="modal-actions"><button type="button" className="secondary-btn" onClick={() => setEditingUser(null)}>Отмена</button><button className="primary-btn" type="submit">Сохранить изменения <Check size={15} /></button></div>
          </form>
        </section>
      </div>}
      {toast && <div className="toast"><Check size={16} /> {toast}</div>}
    </div>
  );
}

function Stat({ icon: Icon, label, value, tone, hint }) {
  return <div className="panel stat-card"><div className={"stat-icon " + tone}><Icon size={19} /></div><div className="stat-label">{label}</div><div className="stat-value">{value}</div><div className="stat-hint">{hint}</div></div>;
}

export default App;
