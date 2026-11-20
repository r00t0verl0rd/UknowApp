import { useCallback, useEffect } from "react";
import { useAuthState, useChatState, useDirectoryState, useGraphState, usePersonalChatState, useSettingsState, useUiState } from "../hooks/useAppState.js";
import Activity from "lucide-react/dist/esm/icons/activity.js";
import Layers from "lucide-react/dist/esm/icons/layers.js";
import Check from "lucide-react/dist/esm/icons/check.js";
import LogOut from "lucide-react/dist/esm/icons/log-out.js";
import MessageCircle from "lucide-react/dist/esm/icons/message-circle.js";
import Users from "lucide-react/dist/esm/icons/users.js";
import X from "lucide-react/dist/esm/icons/x.js";
import Moon from "lucide-react/dist/esm/icons/moon.js";
import Sun from "lucide-react/dist/esm/icons/sun.js";
import Info from "lucide-react/dist/esm/icons/info.js";
import Bell from "lucide-react/dist/esm/icons/bell.js";
import BellOff from "lucide-react/dist/esm/icons/bell-off.js";
import BoardsPage from "../modules/boards/BoardsPage.jsx";
import UsersModule from "../modules/users/UsersModule.jsx";
import ChatsModule from "../modules/conversations/ChatsModule.jsx";
import AdministrationModule from "../modules/administration/AdministrationModule.jsx";
import LoginPage from "../modules/authentication/LoginPage.jsx";
import { usePushNotificationsState } from "../hooks/notifications/usePushNotificationsState.js";
import { useAuthController } from "../hooks/authentication/useAuthController.js";
import { usePanelDataState } from "../hooks/app/usePanelDataState.js";

// Composition root: соединяет общие контроллеры, навигацию и страницы модулей.
export default function App() {
  const authState = useAuthState();
  const { auth, setAuth, profile, setProfile, login, setLogin, password, setPassword } = authState;
  const { theme, toggleTheme } = useSettingsState();
  const { teacherGraph, setTeacherGraph } = useGraphState();
  const chatState = useChatState();
  const { draft, setDraft, attachment, setAttachment, chats, setChats,
    selectedChat, setSelectedChat, messages, setMessages } = chatState;
  const personalState = usePersonalChatState();
  const { setPersonalChats } = personalState;
  const {
    page, setPage, error, setError, toast, setToast, modal, setModal,
  } = useUiState();
  const directory = useDirectoryState();
  const { request, refresh, panelReady } = usePanelDataState({
    auth, page, selectedChat, setAuth, setProfile, setError, setChats,
    setPersonalChats, setUsers: directory.setUsers, setOverview: directory.setOverview, setTeacherGraph, setPage,
    setSelectedChat, setMessages,
  });
  const notify = useCallback(message => {
    setToast(message);
    window.setTimeout(() => setToast(""), 2600);
  }, [setToast]);
  const {
    pushState, pushBusy, setPushState, setPushBusy,
    togglePushNotifications, pushButtonTitle,
  } = usePushNotificationsState({ auth, selectedChat, notify, setError });
  const { signIn, signOut } = useAuthController({
    authState, setError, setPage, setPushBusy, setPushState, setTeacherGraph,
    setUsers: directory.setUsers, setOverview: directory.setOverview,
    setChats, setPersonalChats, setMessages, setSelectedChat, setDraft, setAttachment, notify,
  });

  useEffect(() => {
    if (auth && profile?.role === "teacher") setPage("chats");
  }, [auth, profile?.role, setPage]);

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

  if (!auth) return <LoginPage theme={theme} toggleTheme={toggleTheme} signIn={signIn} login={login} setLogin={setLogin} password={password} setPassword={setPassword} error={error} />;
  if (!panelReady || !profile) return <div className="login-screen"><div className="empty-state">Загрузка личного кабинета…</div></div>;

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
        {profile.role === "admin" && <>
          {page === "boards" && <BoardsPage />}
          <UsersModule
            page={page} profile={profile} directory={directory} request={request}
            refresh={refresh} notify={notify} setError={setError}
            selectedChat={selectedChat} setSelectedChat={setSelectedChat}
            setMessages={setMessages} modal={modal} setModal={setModal}
          />
          <AdministrationModule
            page={page} auth={auth} profile={profile} request={request}
            refresh={refresh} notify={notify} setError={setError}
            setSelectedChat={setSelectedChat} setMessages={setMessages}
          />
        </>}
        {profile.role === "teacher" && page === "graph" && <TeacherStructurePage profile={profile} teacherGraph={teacherGraph} />}
        {["admin", "teacher", "student"].includes(profile.role) && <ChatsModule
          key={profile.role} page={page} auth={auth} profile={profile} request={request}
          chatState={chatState} personalState={personalState}
          users={profile.role === "admin" ? directory.users : []} error={error} modal={modal}
          setPage={setPage} setError={setError} setModal={setModal} notify={notify}
        />}

      </div>
    </main>

    {toast && <div className="toast"><Check/>{toast}</div>}
  </div>;
}