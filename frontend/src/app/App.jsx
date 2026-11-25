import { dynamic } from "@solidjs/web";
import { createMemo, createSignal, createEffect, lazy, Show } from "solid-js";
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
import { installViewportEnvironment } from "../shared/services/viewportEnvironment.js";
import { viewAccountKey, viewPreference, saveViewPreference } from "../shared/services/viewSession.js";
import { readUserSortPreference, saveUserSortPreference } from "../shared/services/userSortPreference.js";
import IconButton from "../shared/components/IconButton.jsx";
import LoginPage from "./authentication/LoginPage.jsx";
import { createPushNotificationsState } from "../shared/state/notifications/createPushNotificationsState.js";
import { createAuthController } from "../shared/state/authentication/createAuthController.js";
import { createPanelDataState } from "../shared/state/app/createPanelDataState.js";
import { workspaceFor, workspaceIcons } from "../workspaces/workspaceRegistry.js";
import WorkspaceLayout from "../workspaces/WorkspaceLayout.jsx";

import { createRestoreFlow } from "../shared/state/administration/createRestoreFlow.js";
const RestoreFlowDialog = lazy(() => import("../features/administration/RestoreFlowDialog.jsx"));

export default function App() {
  createEffect(() => [], () => installViewportEnvironment());
  const [errors, setErrors] = createSignal([]);
  const [notice, setNotice] = createSignal(null);
  const setError = (message) => {
    if (message) setErrors((current) => (current.includes(message) ? current : [...current, message]));
  };
  const dismissError = () => setErrors((current) => current.slice(1));
  const notify = (message, settings = {}) =>
    setNotice({
      message,
      kind: settings.kind === "info" ? "info" : "success",
    });
  createEffect(
    () => [notice()],
    () => {
      if (!notice()) return;
      const timer = window.setTimeout(() => setNotice(null), 6000);
      return () => window.clearTimeout(timer);
    },
  );
  return (
    <>
      <Application setError={setError} notify={notify} />
      <AppToast
        message={errors()[0] || notice()?.message}
        kind={errors().length ? "error" : notice()?.kind}
        onDismiss={errors().length ? dismissError : undefined}
      />
    </>
  );
}
function Application(options) {
  const authState = createAuthState();
  const restoreFlow = createRestoreFlow({
    get auth() { return authState.auth; },
  });
  createEffect(() => [], () => {
    const onStorage = (event) => {
      if (event.key === "uknowapp-session-change" || event.key === "uknowapp-auth" || event.key === null) {
        if (restoreFlow.suppressUnexpectedLogout()) return;
        authState.setProfile(null);
        window.location.reload();
      }
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  });
  const settings = createSettingsState();
  const chatState = createChatState();
  const personalState = createPersonalChatState();
  // The cache belongs to the authenticated application, not a mounted workspace page.
  createEffect(
    () => [authState.auth, authState.profile, chatState.chats, personalState.personalChats],
    ([auth, profile, chats, personalChats]) => {
      const id = viewAccountKey(profile);
      chatState.cache.setScope(auth && id != null ? profile.role + ":" + id : null, [
        ...chats.map(chat => "conversation:" + chat.id),
        ...personalChats.map(chat => "personal:" + chat.id),
      ]);
    },
  );
  const navigation = createUiState();
  const directory = createDirectoryState();
  // Restore view-only preferences after the authenticated user has been identified.
  // Do not persist credentials, private messages, files or destructive dialogs.
  const viewPreferences = [
    ["users.search", () => directory.search, directory.setSearch],
    ["users.sort", () => directory.userSort, directory.setUserSort],
    ["chats.search", () => chatState.chatSearch, chatState.setChatSearch],
    ["chats.filter", () => chatState.chatFilter, chatState.setChatFilter],
    ["chats.messageFilter", () => chatState.messageFilter, chatState.setMessageFilter],
    ["chats.section", () => personalState.chatSection, personalState.setChatSection],
  ];
  let preferencesReadyFor = null;
  createEffect(
    () => [viewAccountKey(authState.profile)],
    ([id]) => {
      preferencesReadyFor = null;
      if (id == null) return;
      for (const [name, , setter] of viewPreferences) {
        const sessionValue = viewPreference(id, name, undefined);
        const saved = name === "users.sort" && authState.profile?.role === "admin"
          ? readUserSortPreference(id, sessionValue ?? "students")
          : sessionValue;
        if (saved !== undefined) setter(saved);
      }
      preferencesReadyFor = id;
    },
  );
  createEffect(
    () => [viewAccountKey(authState.profile), ...viewPreferences.map(([, read]) => read())],
    ([id, ...values]) => {
      if (id == null || preferencesReadyFor !== id) return;
      for (let i = 0; i < viewPreferences.length; i++) {
        const name = viewPreferences[i][0];
        saveViewPreference(id, name, values[i]);
        if (name === "users.sort" && authState.profile?.role === "admin") {
          saveUserSortPreference(id, values[i]);
        }
      }
    },
  );
  const workspace = createMemo(() => workspaceFor(authState.profile));
  const Workspace = dynamic(() => workspace()?.Component);
  const panel = createPanelDataState({
    get auth() {
      return authState.auth;
    },
    get profile() { return authState.profile; },
    setAuth: authState.setAuth,
    setProfile: authState.setProfile,
    setError: options.setError,
    setChats: chatState.setChats,
    setPersonalChats: personalState.setPersonalChats,
    setUsers: directory.setUsers,
    setOverview: directory.setOverview,
    setSelectedChat: chatState.setSelectedChat,
    setMessages: chatState.setMessages,
    restoreFlow,
  });
  const workspacePage = () =>
    workspace()?.pages.includes(navigation.page) ? navigation.page : workspace()?.pages[0];
  const inDialogs = () => authState.auth && workspacePage() === "chats";
  const foregroundChat = () =>
    inDialogs() && document.visibilityState === "visible" && document.hasFocus()
      ? chatState.selectedChat
      : null;
  const activeChat = () =>
    chatState.messagesViewportRef.current?.isConnected ? foregroundChat() : null;
  const acknowledgeVisible = createConversationSync({
    cache: chatState.cache,
    get auth() {
      return workspace() && authState.auth;
    },
    get inDialogs() { return inDialogs(); },
    get foregroundChat() { return foregroundChat(); },
    get activeChat() { return activeChat(); },
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
    verifySession: panel.verifySession,
    inboxRowRevision: panel.inboxRowRevision,
    setChats: chatState.setChats,
    setPersonalChats: personalState.setPersonalChats,
    setSelectedChat: chatState.setSelectedChat,
    setMessages: chatState.setMessages,
  });
  let handledInitialLink = false;
  createEffect(
    () => [authState.auth, navigation.page, workspace()],
    ([auth, , currentWorkspace]) => {
      if (!auth || !currentWorkspace) return;
      let page = workspacePage();
      if (!handledInitialLink) {
        handledInitialLink = true;
        const id = Number(new URLSearchParams(window.location.search).get("openConversation"));
        if (Number.isSafeInteger(id) && id > 0 && currentWorkspace.pages.includes("chats")) {
          page = "chats";
        }
      }
      navigation.setPage(page, { replace: true });
    },
  );
  const push = createPushNotificationsState({
    get auth() {
      return authState.auth;
    },
    get activeChat() { return activeChat(); },
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
    acknowledgeVisible,
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
    restoreFlow,
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
    <>
    <Show
      when={authState.auth}
      fallback={
        <LoginPage
          theme={settings.theme}
          toggleTheme={settings.toggleTheme}
          signIn={session.signIn}
          restoreRelogin={restoreFlow.needsLogin}
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
    <Show when={restoreFlow.phase && restoreFlow.phase !== "login"}>
      <RestoreFlowDialog flow={restoreFlow} />
    </Show>
    </>
  );
}
