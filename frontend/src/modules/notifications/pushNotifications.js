const API = import.meta.env.VITE_API_BASE_URL || "";

function getPushSupport() {
  if (!window.isSecureContext) {
    return { supported: false, reason: "Push-уведомления работают только через HTTPS" };
  }
  if (!("serviceWorker" in navigator) || !("PushManager" in window) || !("Notification" in window)) {
    return { supported: false, reason: "Этот браузер не поддерживает push-уведомления" };
  }

  const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent) ||
    (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
  const standalone = window.matchMedia("(display-mode: standalone)").matches ||
    navigator.standalone === true;
  if (isIOS && !standalone) {
    return {
      supported: false,
      reason: "На iPhone и iPad добавьте UknowApp на экран «Домой», затем откройте приложение оттуда",
    };
  }
  return { supported: true, reason: "" };
}

function decodeApplicationServerKey(value) {
  const padding = "=".repeat((4 - value.length % 4) % 4);
  const base64 = (value + padding).replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(base64);
  return Uint8Array.from(raw, character => character.charCodeAt(0));
}

async function getRegistration() {
  return navigator.serviceWorker.getRegistration("/") ||
    navigator.serviceWorker.register("/sw.js");
}

async function subscribeToPush(registration) {
  const keyResponse = await fetch(API + "/api/push/public-key", { credentials: "include" });
  const keyData = await keyResponse.json().catch(() => ({}));
  if (!keyResponse.ok || !keyData.enabled || !keyData.public_key) {
    throw new Error(keyData.detail || "Push-уведомления не настроены на сервере");
  }

  let subscription = await registration.pushManager.getSubscription();
  if (!subscription) {
    subscription = await registration.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: decodeApplicationServerKey(keyData.public_key),
    });
  }
  const response = await fetch(API + "/api/push/subscribe", {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(subscription.toJSON()),
  });
  const result = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(result.detail || "Не удалось сохранить подписку на уведомления");
  return subscription;
}

export async function getPushNotificationState() {
  const support = getPushSupport();
  if (!support.supported) {
    return { supported: false, enabled: false, permission: "default", reason: support.reason };
  }

  const permission = Notification.permission;
  if (permission === "denied") {
    return {
      supported: true,
      enabled: false,
      permission,
      reason: "Уведомления запрещены в настройках браузера",
    };
  }
  const registration = await navigator.serviceWorker.getRegistration("/");
  const subscription = await registration?.pushManager.getSubscription();
  return {
    supported: true,
    enabled: Boolean(subscription && permission === "granted"),
    permission,
    reason: "",
  };
}

export async function enablePushNotifications() {
  const support = getPushSupport();
  if (!support.supported) throw new Error(support.reason);

  let permission = Notification.permission;
  if (permission === "default") permission = await Notification.requestPermission();
  if (permission !== "granted") {
    throw new Error(permission === "denied"
      ? "Разрешите уведомления для UknowApp в настройках браузера"
      : "Браузер не разрешил включить уведомления");
  }

  const registration = await getRegistration();
  await subscribeToPush(registration);
}

export async function disablePushNotifications() {
  const registration = await navigator.serviceWorker.getRegistration("/");
  const subscription = await registration?.pushManager.getSubscription();
  if (!subscription) return;

  const response = await fetch(API + "/api/push/subscribe", {
    method: "DELETE",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ endpoint: subscription.endpoint }),
  });
  const result = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(result.detail || "Не удалось отключить push-уведомления");
  await subscription.unsubscribe();
}

export async function detachPushSubscription() {
  try {
    await disablePushNotifications();
  } catch (error) {
    console.warn("UknowApp push detach failed:", error);
  }
}
