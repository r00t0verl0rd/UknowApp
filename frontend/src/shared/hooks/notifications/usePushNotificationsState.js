import { useCallback, useEffect, useState } from "react";
import {
  disablePushNotifications, enablePushNotifications, getPushNotificationState,
} from "../../../features/notifications/pushNotifications.js";

const INITIAL_STATE = {
  supported: false, enabled: false, permission: "default",
  reason: "Проверяем поддержку уведомлений…",
};

export function usePushNotificationsState({ auth, selectedChat, notify, setError }) {
  const [pushState, setPushState] = useState(INITIAL_STATE);
  const [pushBusy, setPushBusy] = useState(false);

  useEffect(() => {
    if (!auth) {
      setPushState({ ...INITIAL_STATE, reason: "Войдите в приложение" });
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

  const togglePushNotifications = useCallback(async () => {
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
  }, [pushBusy, pushState, notify, setError]);

  const pushButtonTitle = !pushState.supported
    ? pushState.reason
    : pushState.permission === "denied"
      ? "Уведомления запрещены в настройках браузера"
      : pushState.enabled ? "Отключить push-уведомления" : "Включить push-уведомления";

  return { pushState, pushBusy, togglePushNotifications, pushButtonTitle, setPushState, setPushBusy };
}
