import { useCallback, useEffect } from "react";
import { useAuthState, useChatState, useDirectoryState, useGraphState, usePersonalChatState, useSettingsState, useUiState } from "../shared/hooks/index.js";
import LoginPage from "./authentication/LoginPage.jsx";
import { usePushNotificationsState } from "../shared/hooks/notifications/usePushNotificationsState.js";
import { useAuthController } from "../shared/hooks/authentication/useAuthController.js";
import { usePanelDataState } from "../shared/hooks/app/usePanelDataState.js";
import { workspaceRegistry, workspaceIcons } from "../workspaces/workspaceRegistry.js";
import WorkspaceLayout from "../workspaces/WorkspaceLayout.jsx";
import AppLoading from "../shared/components/AppLoading.jsx";

export default function App() {
  const authState = useAuthState();
  const { auth, setAuth, profile, setProfile, login, setLogin, password, setPassword } = authState;
  const { theme, toggleTheme } = useSettingsState();
  const { teacherGraph, setTeacherGraph } = useGraphState();
  const chatState = useChatState();
  const { setDraft, setAttachment, selectedChat, setSelectedChat, setChats, setMessages } = chatState;
  const personalState = usePersonalChatState();
  const { setPersonalChats } = personalState;
  const { page, setPage, error, setError, toast, setToast, modal, setModal } = useUiState();
  const directory = useDirectoryState();
  const { request, refresh, panelReady } = usePanelDataState({
    auth, page, selectedChat, setAuth, setProfile, setError, setChats,
    setPersonalChats, setUsers: directory.setUsers, setOverview: directory.setOverview,
    setTeacherGraph, setPage, setSelectedChat, setMessages,
  });
  const notify = useCallback(message => {
    setToast(message);
    window.setTimeout(() => setToast(""), 2600);
  }, [setToast]);
  useEffect(() => {
    if (auth && profile?.role === "teacher") setPage("chats");
  }, [auth, profile?.role, setPage]);

  const push = usePushNotificationsState({ auth, selectedChat, notify, setError });
  const { signIn, signOut } = useAuthController({
    authState, setError, setPage, setPushBusy: push.setPushBusy, setPushState: push.setPushState,
    setTeacherGraph, setUsers: directory.setUsers, setOverview: directory.setOverview,
    setChats, setPersonalChats, setMessages, setSelectedChat, setDraft, setAttachment, notify,
  });

  if (!auth) return <LoginPage theme={theme} toggleTheme={toggleTheme} signIn={signIn}
    login={login} setLogin={setLogin} password={password} setPassword={setPassword} error={error} />;
  if (!panelReady || !profile) return <AppLoading label="Загрузка личного кабинета…" />;

  const workspace = workspaceRegistry[profile.role];
  if (!workspace) return <AppLoading label="Для этой роли пока не настроено рабочее пространство." />;
  const workspacePage = workspace.pages.includes(page) ? page : workspace.pages[0];
  const context = {
    auth, profile, page: workspacePage, setPage, request, refresh, notify, error, setError, modal, setModal,
    chatState, personalState, directory, teacherGraph,
  };
  const pushToggle = (
    <button type="button" className={`push-toggle${push.pushState.enabled ? " active" : ""}`}
      onClick={push.togglePushNotifications} disabled={push.pushBusy}
      title={push.pushBusy ? "Обновляем настройки уведомлений…" : push.pushButtonTitle}
      aria-label={push.pushButtonTitle} aria-pressed={push.pushState.enabled}>
      {push.pushState.enabled ? <workspaceIcons.PushOn size={17}/> : <workspaceIcons.PushOff size={17}/>}
    </button>
  );

  return <WorkspaceLayout role={profile.role} profile={profile} label={workspace.label}
    navigation={workspace.navigation} page={workspacePage} setPage={setPage} theme={theme}
    toggleTheme={toggleTheme} pushToggle={pushToggle} signOut={signOut}
    error={error} setError={setError} toast={toast}>
    <workspace.Component context={context}/>
  </WorkspaceLayout>;
}
