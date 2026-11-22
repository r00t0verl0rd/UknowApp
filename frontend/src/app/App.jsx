import { dynamic } from "@solidjs/web";
import { createMemo, createSignal, createEffect, Show } from "solid-js";
import {
  createAuthState,
  createDirectoryState,
  createSettingsState,
  createUiState,
} from "../shared/state/index.js";
import { createChatState } from "../features/conversations/state/createChatState.js";
import { createPersonalChatState } from "../features/conversations/state/createPersonalChatState.js";
import { createConversationSync } from "../features/conversations/state/createConversationSync.js";
import AppToast from "../shared/components/AppToast.jsx";
import IconButton from "../shared/components/IconButton.jsx";
import LoginPage from "./authentication/LoginPage.jsx";
import { createPushNotificationsState } from "../shared/state/notifications/createPushNotificationsState.js";
import { createAuthController } from "../shared/state/authentication/createAuthController.js";
import { createPanelDataState } from "../shared/state/app/createPanelDataState.js";
import { workspaceRegistry, workspaceIcons } from "../workspaces/workspaceRegistry.js";
import WorkspaceLayout from "../workspaces/WorkspaceLayout.jsx";
export default function App() {
  const [errors, setErrors] = createSignal([]);
  const [notice, setNotice] = createSignal(null);
  const setError = (message) => {
    if (message) setErrors((current) => (current.includes(message) ? current : [...current, message]));
  };
  const dismissError = () => setErrors((current) => current.slice(1));
  const notify = (message) =>
    setNotice({
      message,
    });
  createEffect(
    () => [notice()],
    () => {
      if (!notice()) return;
      const timer = window.setTimeout(() => setNotice(null), 2600);
      return () => window.clearTimeout(timer);
    },
  );
  return (
    <>
      <Application setError={setError} notify={notify} />
      <AppToast
        message={errors()[0] || notice()?.message}
        onDismiss={errors().length ? dismissError : undefined}
      />
    </>
  );
}
function Application(options) {
  const authState = createAuthState();
  const settings = createSettingsState();
  const chatState = createChatState();
  const personalState = createPersonalChatState();
  const navigation = createUiState();
  const directory = createDirectoryState();
  const workspace = createMemo(() => workspaceRegistry[authState.profile?.role] ?? null);
  const Workspace = dynamic(() => workspace()?.Component);
  const panel = createPanelDataState({
    get auth() {
      return authState.auth;
    },
    setAuth: authState.setAuth,
    setProfile: authState.setProfile,
    setError: options.setError,
    setChats: chatState.setChats,
    setPersonalChats: personalState.setPersonalChats,
    setUsers: directory.setUsers,
    setOverview: directory.setOverview,
    setSelectedChat: chatState.setSelectedChat,
    setMessages: chatState.setMessages,
  });
  createConversationSync({
    get auth() {
      return authState.auth;
    },
    get role() {
      return authState.profile?.role;
    },
    get selectedChat() {
      return chatState.selectedChat;
    },
    get messages() {
      return chatState.messages;
    },
    request: panel.request,
    inboxRowRevision: panel.inboxRowRevision,
    setChats: chatState.setChats,
    setPersonalChats: personalState.setPersonalChats,
    setSelectedChat: chatState.setSelectedChat,
    setMessages: chatState.setMessages,
  });
  createEffect(
    () => [authState.auth, authState.profile?.role, navigation.page, navigation.setPage, workspace()],
    () => {
      if (!authState.auth || !authState.profile?.role || !workspace()) return;
      const accessiblePage = workspace().pages.includes(navigation.page)
        ? navigation.page
        : workspace().pages[0];
      navigation.setPage(accessiblePage, {
        replace: true,
      });
    },
  );
  const push = createPushNotificationsState({
    get auth() {
      return authState.auth;
    },
    get selectedChat() {
      return chatState.selectedChat;
    },
    notify: options.notify,
    setError: options.setError,
  });
  const session = createAuthController({
    authState,
    setError: options.setError,
    setPushBusy: push.setPushBusy,
    setPushState: push.setPushState,
    setUsers: directory.setUsers,
    setOverview: directory.setOverview,
    setChats: chatState.setChats,
    setPersonalChats: personalState.setPersonalChats,
    setMessages: chatState.setMessages,
    setSelectedChat: chatState.setSelectedChat,
    setDraft: chatState.setDraft,
    setAttachment: chatState.setAttachment,
    notify: options.notify,
  });
  const workspacePage = () =>
    workspace().pages.includes(navigation.page) ? navigation.page : workspace().pages[0];
  const context = {
    get auth() {
      return authState.auth;
    },
    get profile() {
      return authState.profile;
    },
    get page() {
      return workspacePage();
    },
    setPage: navigation.setPage,
    request: panel.request,
    refresh: panel.refresh,
    notify: options.notify,
    setError: options.setError,
    get modal() {
      return navigation.modal;
    },
    setModal: navigation.setModal,
    chatState,
    personalState,
    directory,
    get inboxLoading() {
      return panel.inboxLoading;
    },
    get adminDataLoading() {
      return panel.adminDataLoading;
    },
  };
  const pushToggle = () => (
    <IconButton
      class={`push-toggle${push.pushState.enabled ? " active" : ""}`}
      onClick={push.togglePushNotifications}
      disabled={push.pushBusy}
      title={push.pushBusy ? "Обновляем настройки уведомлений…" : push.pushButtonTitle}
      aria-label={push.pushButtonTitle}
      aria-pressed={push.pushState.enabled}
    >
      {push.pushState.enabled ? <workspaceIcons.PushOn size={17} /> : <workspaceIcons.PushOff size={17} />}
    </IconButton>
  );
  return (
    <Show
      when={authState.auth}
      fallback={
        <LoginPage
          theme={settings.theme}
          toggleTheme={settings.toggleTheme}
          signIn={session.signIn}
          login={authState.login}
          setLogin={authState.setLogin}
          password={authState.password}
          setPassword={authState.setPassword}
        />
      }
    >
      <Show when={workspace()}>
        <WorkspaceLayout
          role={authState.profile.role}
          profile={authState.profile}
          label={workspace().label}
          navigation={workspace().navigation}
          page={workspacePage()}
          setPage={navigation.setPage}
          theme={settings.theme}
          toggleTheme={settings.toggleTheme}
          pushToggle={pushToggle()}
          signOut={session.signOut}
        >
          <Workspace context={context} />
        </WorkspaceLayout>
      </Show>
    </Show>
  );
}
