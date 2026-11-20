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
import AdditionalPage from "../modules/administration/AdditionalPage.jsx";
import ChatsPage from "../modules/conversations/ChatsPage.jsx";
import ChatDialogs from "../modules/conversations/components/ChatDialogs.jsx";
import StructurePage from "../modules/graph/StructurePage.jsx";
import BoardsPage from "../modules/boards/BoardsPage.jsx";
import UsersPage from "../modules/users/UsersPage.jsx";
import UserDialogs from "../modules/users/components/UserDialogs.jsx";
import LoginPage from "../modules/authentication/LoginPage.jsx";
import { usePushNotificationsState } from "../hooks/notifications/usePushNotificationsState.js";
import { useAuthController } from "../hooks/authentication/useAuthController.js";
import { usePanelDataState } from "../hooks/app/usePanelDataState.js";
import { useUsersController } from "../hooks/users/useUsersController.js";
import { useChatsController } from "../hooks/conversations/useChatsController.js";
import { useAdminDataController } from "../hooks/administration/useAdminDataController.js";

// Composition root: соединяет общие контроллеры, навигацию и страницы модулей.
export default function App() {
  const authState = useAuthState();
  const { auth, setAuth, profile, setProfile, login, setLogin, password, setPassword } = authState;
  const { theme, toggleTheme } = useSettingsState();
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
    userInfo, setUserInfo, issuedCredential, setIssuedCredential, savingUser,
    name, setName, panelLogin, setPanelLogin, role, setRole, additionalInfo,
    setAdditionalInfo, telegramId, setTelegramId, teacherId, setTeacherId,
    studentId, setStudentId, code, setCode, deleteCandidate, setDeleteCandidate,
    deletingUser, disconnectCandidate, setDisconnectCandidate,
    disconnectingTelegram, allTeachers, allStudents,
    studentsByTeacherId, visibleUsers, unassignedStudents, openCreate, openEdit,
    saveUser, regeneratePanelAccessCode, removeUser, confirmRemoveUser, assign,
    disconnectTelegram, confirmDisconnectTelegram, makeCode,
  } = useUsersController({
    request, refresh, notify, setError, selectedChat, setSelectedChat,
    setMessages, modal, setModal, directory,
  });
  const {
    visibleChats, visibleMessages, openChat, openCreatePersonalChat, createPersonalChat,
    confirmDeleteMessage, sendChatMessage, deleteMessageCandidate, deletingMessage,
    setDeleteMessageCandidate,
  } = useChatsController({
    auth, request, profile, chatState, personalState, setPage, setError, setModal,
    notify,
  });
  const {
    pushState, pushBusy, setPushState, setPushBusy,
    togglePushNotifications, pushButtonTitle,
  } = usePushNotificationsState({ auth, selectedChat, notify, setError });
  const { signIn, signOut } = useAuthController({
    authState, setError, setPage, setPushBusy, setPushState, setTeacherGraph,
    setUsers, setOverview, setChats, setPersonalChats, setMessages,
    setSelectedChat, setDraft, setAttachment, setIssuedCredential, notify,
  });
  const {
    dataStats, dataBusy, retentionDays, setRetentionDays, loadDataStats,
    downloadAdminFile, uploadAdminFile, cleanupOldDialogues,
  } = useAdminDataController({
    auth, profile, page, request, refresh, notify, setError, setSelectedChat, setMessages,
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

    <UserDialogs
      modal={modal} setModal={setModal} assign={assign}
      teacherId={teacherId} setTeacherId={setTeacherId}
      allTeachers={allTeachers} studentId={studentId} setStudentId={setStudentId}
      allStudents={allStudents} saveUser={saveUser} name={name} setName={setName}
      panelLogin={panelLogin} setPanelLogin={setPanelLogin} role={role} setRole={setRole}
      additionalInfo={additionalInfo} setAdditionalInfo={setAdditionalInfo}
      telegramId={telegramId} setTelegramId={setTelegramId} users={users}
      savingUser={savingUser} regeneratePanelAccessCode={regeneratePanelAccessCode}
      removeUser={removeUser} deleteCandidate={deleteCandidate}
      setDeleteCandidate={setDeleteCandidate} deletingUser={deletingUser}
      confirmRemoveUser={confirmRemoveUser} disconnectCandidate={disconnectCandidate}
      setDisconnectCandidate={setDisconnectCandidate} disconnectingTelegram={disconnectingTelegram}
      confirmDisconnectTelegram={confirmDisconnectTelegram}
      issuedCredential={issuedCredential} setIssuedCredential={setIssuedCredential}
      notify={notify} code={code} setCode={setCode}
    />
    <ChatDialogs
      modal={modal} setModal={setModal} users={users}
      createPersonalChat={createPersonalChat} error={error} setError={setError}
      deleteMessageCandidate={deleteMessageCandidate} selectedChat={selectedChat}
      deletingMessage={deletingMessage} setDeleteMessageCandidate={setDeleteMessageCandidate}
      confirmDeleteMessage={confirmDeleteMessage}
    />
    {toast && <div className="toast"><Check/>{toast}</div>}
  </div>;
}