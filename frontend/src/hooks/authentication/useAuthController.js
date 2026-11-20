import { useCallback } from "react";
import { detachPushSubscription, enablePushNotifications, getPushNotificationState } from "../../modules/notifications/pushNotifications.js";
import { signInRequest, signOutRequest } from "../../modules/authentication/services/authApi.js";

export function useAuthController({
  authState, setError, setPage, setPushBusy, setPushState,
  setTeacherGraph, setUsers, setOverview, setChats, setPersonalChats,
  setMessages, setSelectedChat, setDraft, setAttachment,
  notify,
}) {
  const { login, password, setAuth, setProfile, setPassword } = authState;

  const signIn = useCallback(async event => {
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
      const result = await signInRequest(login.trim(), password);
      setPushBusy(true);
      try {
        await enablePushNotifications();
        setPushState(await getPushNotificationState());
      } catch {
        const state = await getPushNotificationState().catch(() => null);
        if (state) setPushState(state);
        if (state?.supported && state.permission !== "denied") {
          notify("Чтобы включить уведомления, нажмите на значок колокольчика");
        }
      } finally {
        setPushBusy(false);
      }
      localStorage.setItem("uknowapp-auth", "1");
      sessionStorage.removeItem("uknowapp-auth");
      setProfile(result);
      setPage(["student", "teacher"].includes(result.role) ? "chats" : "graph");
      setAuth("1");
      setPassword("");
    } catch (error) {
      setError(error.message || "Не удалось войти");
    }
  }, [login, password, setError, setPushBusy, setPushState, notify, setProfile, setPage, setAuth, setPassword]);

  const signOut = useCallback(async () => {
    try {
      await detachPushSubscription();
      await signOutRequest();
    } catch {
      // Clear the local view even when the server is temporarily unreachable.
    }
    localStorage.removeItem("uknowapp-auth");
    sessionStorage.removeItem("uknowapp-auth");
    setAuth("");
    setProfile(null);
    setTeacherGraph(null);
    setUsers([]);
    setOverview(null);
    setChats([]);
    setPersonalChats([]);
    setMessages([]);
    setSelectedChat(null);
    setDraft("");
    setAttachment(null);
  }, [setAuth, setProfile, setTeacherGraph, setUsers, setOverview, setChats, setPersonalChats, setMessages, setSelectedChat, setDraft, setAttachment]);

  return { signIn, signOut };
}
