import { useCallback, useEffect, useState } from "react";
import { useAuthState, useDirectoryState, useSettingsState, useUiState } from "../shared/hooks/index.js";
import { useChatState } from "../features/conversations/hooks/useChatState.js";
import { usePersonalChatState } from "../features/conversations/hooks/usePersonalChatState.js";
import { useConversationSync } from "../features/conversations/hooks/useConversationSync.js";
import AppToast from "../shared/components/AppToast.jsx";
import LoginPage from "./authentication/LoginPage.jsx";
import { usePushNotificationsState } from "../shared/hooks/notifications/usePushNotificationsState.js";
import { useAuthController } from "../shared/hooks/authentication/useAuthController.js";
import { usePanelDataState } from "../shared/hooks/app/usePanelDataState.js";
import { workspaceRegistry, workspaceIcons } from "../workspaces/workspaceRegistry.js";
import WorkspaceLayout from "../workspaces/WorkspaceLayout.jsx";

export default function App() {
  const [errors, setErrors] = useState([]);
  const [notice, setNotice] = useState(null);
  const setError = useCallback(message => {
    if (message) setErrors(current => current.includes(message) ? current : [...current, message]);
  }, []);
  const dismissError = useCallback(() => setErrors(current => current.slice(1)), []);
  const notify = useCallback(message => setNotice({ message }), []);
  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(() => setNotice(null), 2600);
    return () => window.clearTimeout(timer);
  }, [notice]);

  return <>
    <Application setError={setError} notify={notify}/>
    <AppToast message={errors[0] || notice?.message} onDismiss={errors.length ? dismissError : undefined}/>
  </>;
}

function Application({ setError, notify }) {
  const authState = useAuthState();
  const { auth, setAuth, profile, setProfile, login, setLogin, password, setPassword } = authState;
  const { theme, toggleTheme } = useSettingsState();
  const chatState = useChatState();
  const { setDraft, setAttachment, selectedChat, setSelectedChat, setChats, setMessages } = chatState;
  const personalState = usePersonalChatState();
  const { setPersonalChats } = personalState;
  const { page, setPage, modal, setModal } = useUiState();
  const directory = useDirectoryState();
  const workspace = profile ? workspaceRegistry[profile.role] : null;
  const { request, refresh, inboxRowRevision, inboxLoading, adminDataLoading } = usePanelDataState({
    auth, setAuth, setProfile, setError, setChats,
    setPersonalChats, setUsers: directory.setUsers, setOverview: directory.setOverview,
    setSelectedChat, setMessages,
  });
  useConversationSync({
    auth, role: profile?.role, selectedChat, messages: chatState.messages, request, inboxRowRevision,
    setChats, setPersonalChats, setSelectedChat, setMessages,
  });

  useEffect(() => {
    if (!auth || !profile?.role || !workspace) return;
    const accessiblePage = workspace.pages.includes(page) ? page : workspace.pages[0];
    setPage(accessiblePage, { replace: true });
  }, [auth, profile?.role, page, setPage, workspace]);

  const push = usePushNotificationsState({ auth, selectedChat, notify, setError });
  const { signIn, signOut } = useAuthController({
    authState, setError, setPushBusy: push.setPushBusy, setPushState: push.setPushState,
    setUsers: directory.setUsers, setOverview: directory.setOverview,
    setChats, setPersonalChats, setMessages, setSelectedChat, setDraft, setAttachment, notify,
  });

  if (!auth) return <LoginPage theme={theme} toggleTheme={toggleTheme} signIn={signIn}
    login={login} setLogin={setLogin} password={password} setPassword={setPassword} />;
  if (!workspace) return null;

  const workspacePage = workspace.pages.includes(page) ? page : workspace.pages[0];
  const context = {
    auth, profile, page: workspacePage, setPage, request, refresh, notify, setError, modal, setModal,
    chatState, personalState, directory, inboxLoading, adminDataLoading,
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
    toggleTheme={toggleTheme} pushToggle={pushToggle} signOut={signOut}>
    <workspace.Component context={context}/>
  </WorkspaceLayout>;
}
