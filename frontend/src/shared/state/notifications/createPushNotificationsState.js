import { createSignal, createEffect } from "solid-js";
import {
  disablePushNotifications,
  enablePushNotifications,
  getPushNotificationState,
} from "../../../features/notifications/pushNotifications.js";
const INITIAL_STATE = {
  supported: false,
  enabled: false,
  permission: "default",
  reason: "Проверяем поддержку уведомлений…",
};
export function createPushNotificationsState(options) {
  const [pushState, setPushState] = createSignal(INITIAL_STATE);
  const [pushBusy, setPushBusy] = createSignal(false);
  createEffect(
    () => [options.auth],
    () => {
      if (!options.auth) {
        setPushState({
          ...INITIAL_STATE,
          reason: "Войдите в приложение",
        });
        return undefined;
      }
      let active = true;
      getPushNotificationState()
        .then(async (state) => {
          if (state.supported && state.permission === "granted" && !state.enabled) {
            await enablePushNotifications();
            state = await getPushNotificationState();
          }
          if (active) setPushState(state);
        })
        .catch(() => {
          if (active)
            getPushNotificationState()
              .then((state) => {
                if (active) setPushState(state);
              })
              .catch(() => {});
        });
      return () => {
        active = false;
      };
    },
  );
  createEffect(
    () => [options.selectedChat?.id, options.selectedChat?.type],
    () => {
      const respondToPush = (event) => {
        if (event.data?.type !== "UKNOW_CHECK_ACTIVE_CHAT" || !event.ports?.[0]) return;
        event.ports[0].postMessage({
          active:
            document.visibilityState === "visible" &&
            Number(options.selectedChat?.id) === Number(event.data.conversationId) &&
            (options.selectedChat?.type === "personal" ? "personal" : "conversation") ===
              event.data.conversationType,
        });
      };
      navigator.serviceWorker?.addEventListener("message", respondToPush);
      return () => navigator.serviceWorker?.removeEventListener("message", respondToPush);
    },
  );
  const togglePushNotifications = async () => {
    if (pushBusy()) return;
    if (!pushState().supported) {
      options.notify(pushState().reason);
      return;
    }
    if (pushState().permission === "denied") {
      options.notify("Разрешите уведомления для UknowApp в настройках браузера");
      return;
    }
    setPushBusy(true);
    try {
      if (pushState().enabled) {
        await disablePushNotifications();
        options.notify("Push-уведомления отключены");
      } else {
        await enablePushNotifications();
        options.notify("Push-уведомления включены");
      }
      setPushState(await getPushNotificationState());
    } catch (error) {
      options.setError(error.message || "Не удалось изменить настройки уведомлений");
      try {
        setPushState(await getPushNotificationState());
      } catch {
        /* Сохраняем последнее известное состояние. */
      }
    } finally {
      setPushBusy(false);
    }
  };
  const pushButtonTitle = () =>
    !pushState().supported
      ? pushState().reason
      : pushState().permission === "denied"
        ? "Уведомления запрещены в настройках браузера"
        : pushState().enabled
          ? "Отключить push-уведомления"
          : "Включить push-уведомления";
  return {
    get pushState() {
      return pushState();
    },
    get pushBusy() {
      return pushBusy();
    },
    togglePushNotifications,
    get pushButtonTitle() {
      return pushButtonTitle();
    },
    setPushState,
    setPushBusy,
  };
}
