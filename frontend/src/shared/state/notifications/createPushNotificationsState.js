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
          if (state.supported && state.permission === "granted" && !state.enabled && !pushBusy()) {
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
    () => [],
    () => {
      const respondToPush = (event) => {
        if (event.data?.type !== "UKNOW_CHECK_ACTIVE_CHAT" || !event.ports?.[0]) return;
        const chat = options.activeChat;
        event.ports[0].postMessage({
          active:
            Number(chat?.id) === Number(event.data.conversationId) &&
            (chat?.type === "personal" ? "personal" : "conversation") ===
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
      options.notify(pushState().reason, { kind: "info" });
      return;
    }
    if (pushState().permission === "denied") {
      options.notify("Уведомления отключены в настройках устройства. Разрешите их для UknowApp и попробуйте снова.", { kind: "info" });
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
      options.setError(error.message || "Пока не получилось изменить настройки уведомлений. Попробуйте ещё раз.");
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
      ? "Как включить уведомления"
      : pushState().permission === "denied"
        ? "Уведомления отключены в настройках браузера"
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
