import {
  detachPushSubscription,
  syncPushNotifications,
  getPushNotificationState,
} from "../../../features/notifications/pushNotifications.js";
import { signInRequest, signOutRequest } from "../../../app/authentication/services/authApi.js";
import { viewAccountKey, clearViewState } from "../../services/viewSession.js";
export function createAuthController(options) {
  const signIn = async (event) => {
    event.preventDefault();
    if (!options.authState.login.trim()) {
      options.setError("Введите логин");
      return;
    }
    if (!options.authState.password) {
      options.setError("Введите пароль");
      return;
    }
    try {
      await signInRequest(options.authState.login.trim(), options.authState.password);
      localStorage.setItem("uknowapp-session-change", String(Date.now()));
      // Authentication is complete: show the workspace before the optional
      // push permission/subscription flow, which can take several seconds.
      options.setPushBusy(true);
      localStorage.setItem("uknowapp-auth", "1");
      sessionStorage.removeItem("uknowapp-auth");
      options.authState.setProfile(null);
      options.authState.setAuth("1");
      options.authState.setPassword("");
      void (async () => {
        try {
          await syncPushNotifications({ requestPermission: true, login: true });
          const state = await getPushNotificationState();
          if (options.authState.auth) options.setPushState(state);
        } catch {
          const state = await getPushNotificationState().catch(() => null);
          if (options.authState.auth && state) options.setPushState(state);
          if (options.authState.auth && state?.supported && state.permission !== "denied") {
            options.notify("Чтобы включить уведомления, нажмите на значок колокольчика");
          }
        } finally {
          options.setPushBusy(false);
        }
      })();
    } catch (error) {
      options.setError(error.message || "Не удалось войти");
    }
  };
  const signOut = async () => {
    const userId = viewAccountKey(options.authState.profile);
    options.authState.setProfile(null);
    options.setPushBusy(true);
    try {
      await detachPushSubscription().catch(() => {});
      await signOutRequest();
    } catch {
      // Очищаем данные экрана, даже если сервер временно недоступен.
    }
    localStorage.removeItem("uknowapp-auth");
    sessionStorage.removeItem("uknowapp-auth");
    clearViewState(userId);
    options.authState.setAuth("");
    options.authState.setProfile(null);
    options.setUsers([]);
    options.setOverview(null);
    options.setChats([]);
    options.setPersonalChats([]);
    options.setMessages([]);
    options.setSelectedChat(null);
    options.setDraft("");
    options.setAttachments([]);
    window.location.reload();
  };
  return {
    signIn,
    signOut,
  };
}
