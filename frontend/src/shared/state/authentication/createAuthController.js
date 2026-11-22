import {
  detachPushSubscription,
  enablePushNotifications,
  getPushNotificationState,
} from "../../../features/notifications/pushNotifications.js";
import { signInRequest, signOutRequest } from "../../../app/authentication/services/authApi.js";
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
      const result = await signInRequest(options.authState.login.trim(), options.authState.password);
      options.setPushBusy(true);
      try {
        await enablePushNotifications();
        options.setPushState(await getPushNotificationState());
      } catch {
        const state = await getPushNotificationState().catch(() => null);
        if (state) options.setPushState(state);
        if (state?.supported && state.permission !== "denied") {
          options.notify("Чтобы включить уведомления, нажмите на значок колокольчика");
        }
      } finally {
        options.setPushBusy(false);
      }
      localStorage.setItem("uknowapp-auth", "1");
      sessionStorage.removeItem("uknowapp-auth");
      options.authState.setProfile(result);
      options.authState.setAuth("1");
      options.authState.setPassword("");
    } catch (error) {
      options.setError(error.message || "Не удалось войти");
    }
  };
  const signOut = async () => {
    try {
      await detachPushSubscription();
      await signOutRequest();
    } catch {
      // Очищаем данные экрана, даже если сервер временно недоступен.
    }
    localStorage.removeItem("uknowapp-auth");
    sessionStorage.removeItem("uknowapp-auth");
    options.authState.setAuth("");
    options.authState.setProfile(null);
    options.setUsers([]);
    options.setOverview(null);
    options.setChats([]);
    options.setPersonalChats([]);
    options.setMessages([]);
    options.setSelectedChat(null);
    options.setDraft("");
    options.setAttachment(null);
  };
  return {
    signIn,
    signOut,
  };
}
