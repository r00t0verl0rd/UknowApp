import { useCallback, useEffect, useState } from "react";
import { useAuthState, useChatState, useDirectoryState, useGraphState, usePersonalChatState, useSettingsState, useUiState } from "../hooks/useAppState.js";
import Activity from "lucide-react/dist/esm/icons/activity.js";
import Layers from "lucide-react/dist/esm/icons/layers.js";
import Check from "lucide-react/dist/esm/icons/check.js";
import LogOut from "lucide-react/dist/esm/icons/log-out.js";
import MessageCircle from "lucide-react/dist/esm/icons/message-circle.js";
import RefreshCw from "lucide-react/dist/esm/icons/refresh-cw.js";
import Trash2 from "lucide-react/dist/esm/icons/trash-2.js";
import Users from "lucide-react/dist/esm/icons/users.js";
import X from "lucide-react/dist/esm/icons/x.js";
import Copy from "lucide-react/dist/esm/icons/copy.js";
import Moon from "lucide-react/dist/esm/icons/moon.js";
import Sun from "lucide-react/dist/esm/icons/sun.js";
import Info from "lucide-react/dist/esm/icons/info.js";
import Bell from "lucide-react/dist/esm/icons/bell.js";
import BellOff from "lucide-react/dist/esm/icons/bell-off.js";
import AdditionalPage from "../modules/administration/AdditionalPage.jsx";
import ChatsPage from "../modules/conversations/ChatsPage.jsx";
import StructurePage from "../modules/graph/StructurePage.jsx";
import BoardsPage from "../modules/boards/BoardsPage.jsx";
import UsersPage from "../modules/users/UsersPage.jsx";
import LoginPage from "../modules/authentication/LoginPage.jsx";
import { detachPushSubscription, disablePushNotifications, enablePushNotifications, getPushNotificationState } from "../modules/notifications/pushNotifications.js";
import { usePanelDataState } from "../hooks/app/usePanelDataState.js";
import { useUsersController } from "../hooks/users/useUsersController.js";
import { useChatsController } from "../hooks/conversations/useChatsController.js";

const API = import.meta.env.VITE_API_BASE_URL || "";

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
    auth, setAuth, profile, setProfile, login, setLogin, password, setPassword,
  } = useAuthState();
  const { theme, setTheme } = useSettingsState();
  const { teacherGraph, setTeacherGraph } = useGraphState();
  const chatState = useChatState();
  const {
    draft, setDraft, attachment, setAttachment, chats, setChats,
    selectedChat, setSelectedChat, messages, setMessages, messagesViewportRef,
    chatSearch, setChatSearch, chatFilter, setChatFilter,
    messageFilter, setMessageFilter,
  } = chatState;
  const personalState = usePersonalChatState();
  const { personalChats, setPersonalChats, chatSection, setChatSection } = personalState;
  const {
    page, setPage, error, setError, toast, setToast, modal, setModal,
  } = useUiState();
  const directory = useDirectoryState();
  const [dataStats, setDataStats] = useState(null);
  const [dataBusy, setDataBusy] = useState(false);
  const [retentionDays, setRetentionDays] = useState("30");
  const [pushState, setPushState] = useState({ supported: false, enabled: false, permission: "default", reason: "Проверяем поддержку уведомлений…" });
  const [pushBusy, setPushBusy] = useState(false);
  const { request, refresh } = usePanelDataState({
    auth, page, selectedChat, setAuth, setProfile, setError, setChats,
    setPersonalChats, setUsers: directory.setUsers, setOverview: directory.setOverview, setTeacherGraph, setPage,
    setSelectedChat, setMessages,
  });
  const notify = useCallback(message => {
    setToast(message);
    window.setTimeout(() => setToast(""), 2600);
  }, [setToast]);
  const {
    users, setUsers, overview, setOverview, search, setSearch, userSort, setUserSort,
    userInfo, setUserInfo, issuedCredential, setIssuedCredential, savingUser, setSavingUser,
    name, setName, panelLogin, setPanelLogin, role, setRole, additionalInfo,
    setAdditionalInfo, telegramId, setTelegramId, teacherId, setTeacherId,
    studentId, setStudentId, code, setCode, deleteCandidate, setDeleteCandidate,
    deletingUser, setDeletingUser, disconnectCandidate, setDisconnectCandidate,
    disconnectingTelegram, setDisconnectingTelegram, allTeachers, allStudents,
    studentsByTeacherId, visibleUsers, unassignedStudents, openCreate, openEdit,
    saveUser, regeneratePanelAccessCode, removeUser, confirmRemoveUser, assign,
    unassignStudent, disconnectTelegram, confirmDisconnectTelegram, makeCode,
  } = useUsersController({
    request, refresh, notify, setError, selectedChat, setSelectedChat,
    setMessages, modal, setModal, directory,
  });
  const {
    visibleChats, visibleMessages, openChat, createPersonalChat,
    confirmDeleteMessage, sendChatMessage,
  } = useChatsController({
    request, profile, chatState, personalState, setPage, setError, setModal,
    notify, deleteMessageCandidate, deletingMessage, setDeletingMessage,
    setDeleteMessageCandidate,
  });

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
  useEffect(() => {
    if (auth && profile?.role === "teacher") setPage("chats");
  }, [auth, profile?.role, setPage]);

  useEffect(() => {
    if (!auth) {
      setPushState({ supported: false, enabled: false, permission: "default", reason: "Войдите в приложение" });
      return undefined;
    }
    let active = true;
    getPushNotificationState()
      .then(async state => {
        if (state.supported && state.permission === "granted" && !state.enabled) {
          await enablePushNotifications();
          state = await getPushNotificationState();
        }
        if (active) setPushState(state);
      })
      .catch(() => {
        if (active) getPushNotificationState()
          .then(state => { if (active) setPushState(state); })
          .catch(() => {});
      });
    return () => { active = false; };
  }, [auth]);

  useEffect(() => {
    const respondToPush = event => {
      if (event.data?.type !== "UKNOW_CHECK_ACTIVE_CHAT" || !event.ports?.[0]) return;
      event.ports[0].postMessage({
        active: document.visibilityState === "visible"
          && Number(selectedChat?.id) === Number(event.data.conversationId)
          && (selectedChat?.type === "personal" ? "personal" : "conversation") === event.data.conversationType,
      });
    };
    navigator.serviceWorker?.addEventListener("message", respondToPush);
    return () => navigator.serviceWorker?.removeEventListener("message", respondToPush);
  }, [selectedChat?.id, selectedChat?.type]);

  // Notification links restore the exact conversation after the inbox data is loaded.
  useEffect(() => {
    if (!auth || !profile) return;
    const params = new URLSearchParams(window.location.search);
    const conversationId = Number(params.get("openConversation"));
    if (!conversationId) return;
    const personal = params.get("type") === "personal";
    const source = personal ? personalChats : chats;
    const chat = source.find(item => Number(item.id) === conversationId);
    if (!chat) return;
    window.history.replaceState({}, "", window.location.pathname + window.location.hash);
    setPage("chats");
    if (personal) setChatSection("personal");
    setSelectedChat(chat);
    request((personal ? "/api/panel/personal-conversations/" : "/api/panel/conversations/") + chat.id + "/messages")
      .then(setMessages)
      .catch(error => setError(error.message));
  }, [auth, profile, chats, personalChats, request]);

  useEffect(() => {
    localStorage.setItem("uknowapp-theme-v2", theme);
    document.documentElement.dataset.theme = theme;
  }, [theme]);

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
      anchor.download = ({ full: "uknowapp-full-backup.zip", database: "uknowapp-backup.sqlite3", media: "uknowapp-media.zip" })[kind] || "uknowapp-backup";
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
    const warning = kind === "full"
      ? "Полностью восстановить UknowApp из этой копии? Текущая база данных и все медиафайлы будут заменены."
      : "Заменить текущую базу данных загруженной копией? Все текущие данные будут перезаписаны.";
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
      notify(kind === "full" ? "Полная резервная копия восстановлена. Перезагрузите панель." : "База данных восстановлена. Перезагрузите панель.");
      await loadDataStats();
      if (kind === "full" || kind === "database") {
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

  function toggleTheme() {
    setTheme(current => current === "dark-soft" ? "light" : "dark-soft");
  }

  async function togglePushNotifications() {
    if (pushBusy) return;
    if (!pushState.supported) {
      notify(pushState.reason);
      return;
    }
    if (pushState.permission === "denied") {
      notify("Разрешите уведомления для UknowApp в настройках браузера");
      return;
    }
    setPushBusy(true);
    setError("");
    try {
      if (pushState.enabled) {
        await disablePushNotifications();
        notify("Push-уведомления отключены");
      } else {
        await enablePushNotifications();
        notify("Push-уведомления включены");
      }
      setPushState(await getPushNotificationState());
    } catch (error) {
      setError(error.message || "Не удалось изменить настройки уведомлений");
      try { setPushState(await getPushNotificationState()); } catch { /* Keep the last known state. */ }
    } finally {
      setPushBusy(false);
    }
  }

  const pushButtonTitle = !pushState.supported
    ? pushState.reason
    : pushState.permission === "denied"
      ? "Уведомления запрещены в настройках браузера"
      : pushState.enabled ? "Отключить push-уведомления" : "Включить push-уведомления";

  const pushToggle = (
    <button
      type="button"
      className={`push-toggle${pushState.enabled ? " active" : ""}`}
      onClick={togglePushNotifications}
      disabled={pushBusy}
      title={pushBusy ? "Обновляем настройки уведомлений…" : pushButtonTitle}
      aria-label={pushButtonTitle}
      aria-pressed={pushState.enabled}
    >
      {pushState.enabled ? <Bell size={17}/> : <BellOff size={17}/>}
    </button>
  );

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
      // Enable push by default immediately after successful login, while the
      // browser still has the login button's user activation.
      setPushBusy(true);
      try {
        await enablePushNotifications();
        setPushState(await getPushNotificationState());
      } catch (pushError) {
        const state = await getPushNotificationState().catch(() => null);
        if (state) setPushState(state);
        if (state?.supported && state.permission !== "denied") {
          notify("Чтобы включить уведомления, нажмите на значок колокольчика");
        }
      } finally {
        setPushBusy(false);
      }
      localStorage.setItem("uknowapp-auth", "1"); sessionStorage.removeItem("uknowapp-auth"); setProfile(result); setPage(["student", "teacher"].includes(result.role) ? "chats" : "graph"); setAuth("1"); setPassword("");
    } catch (e) {
      setError(e.message || "Не удалось войти");
    }
  }

  async function signOut() {
    try {
      await detachPushSubscription();
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

  if (!auth) return <LoginPage theme={theme} toggleTheme={toggleTheme} signIn={signIn} login={login} setLogin={setLogin} password={password} setPassword={setPassword} error={error} />;

  return <div className="shell chats-shell">
    <aside className="sidebar">
      <div className="brand"><img src="/logo.png" alt="" /><span>Uknow<span>App</span></span></div>
      <div className="school-label">{profile?.role === "admin" ? "УПРАВЛЕНИЕ ШКОЛОЙ" : profile?.role === "student" ? "ЛИЧНЫЙ КАБИНЕТ УЧЕНИКА" : "РАБОЧЕЕ МЕСТО УЧИТЕЛЯ"}</div>
      <nav>
        {profile?.role === "admin" && <button className={page === "graph" ? "active" : ""} onClick={() => setPage("graph")}><Activity/>Структура</button>}
        {(profile?.role === "admin" || profile?.role === "teacher") && <button className={page === "chats" ? "active" : ""} onClick={() => setPage("chats")}><MessageCircle/>Диалоги</button>}
        {profile?.role === "teacher" && <button className={page === "graph" ? "active" : ""} onClick={() => setPage("graph")}><Activity/>Структура</button>}
        {profile?.role === "admin" && <button className={page === "users" ? "active" : ""} onClick={() => setPage("users")}><Users/>Пользователи</button>}
        {profile?.role === "admin" && <button className={page === "boards" ? "active" : ""} onClick={() => setPage("boards")}><Layers/>Доски</button>}
        {profile?.role === "student" && <button className={page === "chats" ? "active" : ""} onClick={() => setPage("chats")}><MessageCircle/>Диалоги</button>}
      </nav>
      <div className="sidebar-bottom">
        {profile?.role === "admin" && <button type="button" className={`logout desktop-admin-extra${page === "additional" ? " active" : ""}`} onClick={() => setPage("additional")}><Info size={18}/>Дополнительно</button>}
        <button type="button" className="logout desktop-sidebar-logout" onClick={signOut}><LogOut size={18}/>Выход</button>
        <div className="mobile-quick-actions">
          {pushToggle}
          <button type="button" className="theme-toggle" onClick={toggleTheme} title={theme === "dark-soft" ? "Светлая тема" : "Тёмная soft-тема"} aria-label={theme === "dark-soft" ? "Включить светлую тему" : "Включить тёмную soft-тему"}>
            {theme === "dark-soft" ? <Sun size={17}/> : <Moon size={17}/>}
          </button>
          <button className="logout" onClick={signOut} title="Выйти" aria-label="Выйти"><LogOut/></button>
        </div>
      </div>
    </aside>

    <main className="main chats-main">
      <header className="topbar">
        <small className="topbar-user">{profile?.full_name}</small>
        <div className="topbar-actions">
          {pushToggle}
          <button type="button" className="theme-toggle" onClick={toggleTheme} title={theme === "dark-soft" ? "Светлая тема" : "Тёмная soft-тема"} aria-label={theme === "dark-soft" ? "Включить светлую тему" : "Включить тёмную soft-тему"}>
            {theme === "dark-soft" ? <Sun size={17}/> : <Moon size={17}/>}
          </button>
        </div>
      </header>
      <div className={"content" + (page === "chats" ? " chats-content" : "")}>
        {error && <div className="alert alert-row">{error}<button onClick={() => setError("")}><X/></button></div>}
        {page === "graph" && <StructurePage profile={profile} teacherGraph={teacherGraph} overview={overview} openCreate={openCreate} allTeachers={allTeachers} studentsByTeacherId={studentsByTeacherId} openEdit={openEdit} setTeacherId={setTeacherId} setStudentId={setStudentId} allStudents={allStudents} setModal={setModal} unassignedStudents={unassignedStudents} />}
        {page === "boards" && profile?.role === "admin" && <BoardsPage />}
        {page === "users" && <UsersPage visibleUsers={visibleUsers} search={search} setSearch={setSearch} userSort={userSort} setUserSort={setUserSort} openCreate={openCreate} disconnectTelegram={disconnectTelegram} makeCode={makeCode} userInfo={userInfo} setUserInfo={setUserInfo} openEdit={openEdit} removeUser={removeUser} />}
        {page === "chats" && <ChatsPage profile={profile} chatSection={chatSection} setChatSection={setChatSection} personalChats={personalChats} setSelectedChat={setSelectedChat} setMessages={setMessages} chatFilter={chatFilter} setChatFilter={setChatFilter} openCreatePersonalChat={openCreatePersonalChat} chatSearch={chatSearch} setChatSearch={setChatSearch} visibleChats={visibleChats} openChat={openChat} selectedChat={selectedChat} setPage={setPage} draft={draft} setDraft={setDraft} messageFilter={messageFilter} setMessageFilter={setMessageFilter} messagesViewportRef={messagesViewportRef} visibleMessages={visibleMessages} messages={messages} setDeleteMessageCandidate={setDeleteMessageCandidate} attachment={attachment} setAttachment={setAttachment} sendChatMessage={sendChatMessage} />}

        {page === "additional" && profile?.role === "admin" && <AdditionalPage dataStats={dataStats} dataBusy={dataBusy} loadDataStats={loadDataStats} downloadAdminFile={downloadAdminFile} uploadAdminFile={uploadAdminFile} retentionDays={retentionDays} setRetentionDays={setRetentionDays} cleanupOldDialogues={cleanupOldDialogues} />}
      </div>
    </main>

    {modal && modal.mode !== "create-personal" && <div className="overlay" onMouseDown={() => setModal(null)}><section className={`modal${modal.mode === "create" ? " create-participant-modal" : modal.mode === "edit" ? " participant-profile-modal" : ""}`} onMouseDown={e => e.stopPropagation()}>
      <div className="modal-head"><div><div className="eyebrow">{modal.mode === "create" ? "НОВЫЙ УЧАСТНИК" : modal.mode === "edit" ? "ПРОФИЛЬ УЧАСТНИКА" : "СВЯЗЬ УЧЕНИКА И УЧИТЕЛЯ"}</div><h2>{modal.mode === "create" ? "Добавить участника" : modal.mode === "edit" ? "Редактировать" : "Назначить ученика"}</h2></div><button className="icon-btn" onClick={() => setModal(null)}><X/></button></div>
      {modal.mode === "assign" ? <form className="stack" onSubmit={assign}>
        <label>Учитель<select value={teacherId} onChange={e => setTeacherId(e.target.value)} required>{allTeachers.map(t => <option value={t.id} key={t.id}>{t.full_name}</option>)}</select></label>
        <label>Ученик<select value={studentId} onChange={e => setStudentId(e.target.value)} required>{allStudents.map(s => <option value={s.id} key={s.id}>{s.full_name}</option>)}</select></label>
        <p className="hint">Если у ученика уже есть активное назначение, оно будет заменено новым.</p>
        <button className="btn primary" disabled={!allStudents.length}>Создать связь</button>
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
        const selected = users.find(user => ["teacher", "student"].includes(user.role) && user.full_name.trim().toLocaleLowerCase("ru") === value);
        if (selected) void createPersonalChat(selected.id);
        else setError("Выберите участника из списка учителей и учеников");
      }}>
        <label>Участник<input name="participant" list="personal-participant-options" placeholder="Начните вводить имя" autoComplete="off" autoFocus required/></label>
        <datalist id="personal-participant-options">{users.filter(user => ["teacher", "student"].includes(user.role)).map(user => <option value={user.full_name} key={user.id}>{user.role === "teacher" ? "Учитель" : "Ученик"}</option>)}</datalist>
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
      <div className="credential-field">
        <div className="credential-field-label">Логин</div>
        <div className="credential-field-value"><b>{issuedCredential.username}</b><button type="button" className="icon-btn" onClick={async () => notify(await copyText(issuedCredential.username) ? "Логин скопирован" : "Не удалось скопировать логин")} aria-label="Скопировать логин"><Copy size={16}/></button></div>
      </div>
      <div className="credential-field credential-field-code">
        <div className="credential-field-label">Код доступа</div>
        <div className="credential-field-value"><b>{issuedCredential.code}</b><button type="button" className="icon-btn" onClick={async () => notify(await copyText(issuedCredential.code) ? "Код доступа скопирован" : "Не удалось скопировать код доступа")} aria-label="Скопировать код доступа"><Copy size={16}/></button></div>
      </div>
      <div className="modal-actions credential-actions"><button type="button" className="btn primary" onClick={async () => notify(await copyText("Логин: " + issuedCredential.username + "\nКод доступа: " + issuedCredential.code) ? "Данные для входа скопированы" : "Не удалось скопировать данные")}><Copy size={16}/>Скопировать данные</button></div>
    </section></div>}
    {code && <div className="overlay" onMouseDown={() => setCode(null)}><section className="modal" onMouseDown={e => e.stopPropagation()}><div className="modal-head"><div><div className="eyebrow">ПОДКЛЮЧЕНИЕ TELEGRAM</div><h2>{code.full_name}</h2></div><button className="icon-btn" onClick={() => setCode(null)}><X/></button></div><div className="invite-code">{code.code}</div><p className="hint">{code.shared_access ? `Это единый код ${code.role === "student" ? "ученика" : "учителя"}: он подходит для входа в веб-панель вместе с логином и для подключения Telegram. Он действует, пока администратор не заменит его новым.` : "Передайте этот код ученику для подключения Telegram. Он действует до первого успешного подключения и используется один раз."}</p><div className="modal-actions"><button className="btn ghost" onClick={() => setCode(null)}>Закрыть</button><button className="btn primary" onClick={async () => notify(await copyText(code.code) ? "Код скопирован" : "Не удалось скопировать код")}><Copy/>Скопировать</button></div></section></div>}
    {toast && <div className="toast"><Check/>{toast}</div>}
  </div>;
}