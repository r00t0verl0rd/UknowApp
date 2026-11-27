import { fetchApi } from "../../shared/services/api.js";

function getPushSupport() {
  const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent) ||
    (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
  const standalone = window.matchMedia("(display-mode: standalone)").matches ||
    navigator.standalone === true;
  // Для push на iOS Safari приложение нужно установить.
  if (isIOS && !standalone) {
    return {
      supported: false,
      reason: "На iPhone уведомления работают в UknowApp, открытом с экрана «Домой». Если значка ещё нет, в Safari нажмите «Поделиться» → «На экран Домой». Затем откройте приложение с иконки и включите уведомления.",
    };
  }
  if (!window.isSecureContext) {
    return { supported: false, reason: "Для уведомлений нужно открыть UknowApp по защищённому адресу HTTPS." };
  }
  if (!("serviceWorker" in navigator) || !("PushManager" in window) || !("Notification" in window)) {
    return { supported: false, reason: "В этом браузере уведомления пока недоступны. Попробуйте открыть UknowApp в другом браузере." };
  }
  return { supported: true, reason: "" };
}

function decodeApplicationServerKey(value) {
  const padding = "=".repeat((4 - value.length % 4) % 4);
  const base64 = (value + padding).replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(base64);
  return Uint8Array.from(raw, character => character.charCodeAt(0));
}

// Отключение push действует только на этом устройстве.
const OPT_OUT = "uknowapp-push-disabled";
let synchronizedEndpoint = null;
let operation = Promise.resolve();
let detached = false;

function optedOut() {
  return localStorage.getItem(OPT_OUT) === "1";
}

function exclusive(work) {
  const result = operation.then(work);
  operation = result.catch(() => {});
  return result;
}

async function getRegistration() {
  const existing = await navigator.serviceWorker.getRegistration("/");
  const registration = existing || await navigator.serviceWorker.register("/sw.js");
  return registration.active ? registration : navigator.serviceWorker.ready || registration;
}

function matchesKey(subscription, key) {
  const current = subscription.options?.applicationServerKey;
  if (!current) return true; // Some browsers do not expose the key.
  const bytes = new Uint8Array(current);
  return bytes.length === key.length && bytes.every((byte, index) => byte === key[index]);
}

async function removeServerSubscription(endpoint) {
  const response = await fetchApi("/api/push/subscribe", {
    method: "DELETE",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ endpoint }),
  });
  if (!response.ok) throw new Error("Пока не получилось отключить уведомления. Попробуйте ещё раз.");
}

async function saveSubscription(subscription) {
  const response = await fetchApi("/api/push/subscribe", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(subscription.toJSON()),
  });
  if (response.status === 410) return false;
  const result = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(result.detail || "Пока не получилось включить уведомления. Попробуйте ещё раз.");
  return true;
}

async function subscribeToPush(registration) {
  synchronizedEndpoint = null;
  const keyResponse = await fetchApi("/api/push/public-key");
  const keyData = await keyResponse.json().catch(() => ({}));
  if (!keyResponse.ok || !keyData.enabled || !keyData.public_key) {
    throw new Error(keyData.detail || "Уведомления пока не настроены в UknowApp. Попробуйте чуть позже.");
  }
  const key = decodeApplicationServerKey(keyData.public_key);
  let subscription = await registration.pushManager.getSubscription();
  const obsolete = new Set();
  async function discard() {
    obsolete.add(subscription.endpoint);
    await subscription.unsubscribe();
    subscription = null;
  }
  if (subscription && (!matchesKey(subscription, key) ||
      (subscription.expirationTime != null && subscription.expirationTime <= Date.now()))) {
    await discard();
  }
  for (let attempt = 0; attempt < 2; attempt++) {
    if (detached || optedOut()) return;
    if (!subscription) {
      subscription = await registration.pushManager.subscribe({
        userVisibleOnly: true, applicationServerKey: key,
      });
    }
    if (detached || optedOut()) return;
    if (await saveSubscription(subscription)) {
      synchronizedEndpoint = subscription.endpoint;
      for (const endpoint of obsolete) {
        if (endpoint !== subscription.endpoint) await removeServerSubscription(endpoint).catch(() => {});
      }
      return;
    }
    await discard();
  }
  throw new Error("Не удалось обновить устаревшую подписку. Попробуйте ещё раз.");
}

export async function getPushNotificationState() {
  const support = getPushSupport();
  if (!support.supported) return { supported: false, enabled: false, permission: "default", reason: support.reason };
  const permission = Notification.permission;
  if (permission === "denied") {
    return { supported: true, enabled: false, permission, reason: "Уведомления отключены в настройках браузера" };
  }
  const registration = await navigator.serviceWorker.getRegistration("/");
  const subscription = await registration?.pushManager.getSubscription();
  return {
    supported: true,
    enabled: Boolean(!detached && !optedOut() && subscription && subscription.endpoint === synchronizedEndpoint && permission === "granted"),
    permission,
    reason: subscription && subscription.endpoint !== synchronizedEndpoint && !optedOut()
      ? "Подписка ещё не подтверждена сервером" : "",
  };
}

export function syncPushNotifications({ requestPermission = false, login = false } = {}) {
  if (login) detached = false;
  return exclusive(async () => {
    if (detached || optedOut()) return;
    const support = getPushSupport();
    if (!support.supported) {
      if (requestPermission) throw new Error(support.reason);
      return;
    }
    let permission = Notification.permission;
    if (permission === "default" && requestPermission) permission = await Notification.requestPermission();
    if (permission !== "granted") {
      synchronizedEndpoint = null;
      if (!requestPermission) return;
      throw new Error(permission === "denied"
        ? "Уведомления отключены в настройках устройства. Разрешите их для UknowApp и попробуйте снова."
        : "Уведомления пока не включены. Попробуйте ещё раз, когда будет удобно.");
    }
    if (!detached && !optedOut()) await subscribeToPush(await getRegistration());
  });
}

export function enablePushNotifications() {
  localStorage.removeItem(OPT_OUT);
  return syncPushNotifications({ requestPermission: true });
}

async function removeCurrentSubscription() {
  synchronizedEndpoint = null;
  const registration = await navigator.serviceWorker.getRegistration("/");
  const subscription = await registration?.pushManager.getSubscription();
  if (!subscription) return;
  // Отключаем подписку браузера даже при ошибке сети.
  try {
    await removeServerSubscription(subscription.endpoint);
  } finally {
    await subscription.unsubscribe();
  }
}

export function disablePushNotifications() {
  localStorage.setItem(OPT_OUT, "1");
  return exclusive(removeCurrentSubscription);
}

export function detachPushSubscription() {
  detached = true;
  // Выход из аккаунта не отключает push навсегда.
  return exclusive(removeCurrentSubscription).catch(error => {
    console.warn("UknowApp push detach failed:", error);
  });
}
