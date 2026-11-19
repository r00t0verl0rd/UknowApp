const API = import.meta.env.VITE_API_BASE_URL || "";
let initializationStarted = false;

function decodeApplicationServerKey(value) {
  const padding = "=".repeat((4 - value.length % 4) % 4);
  const base64 = (value + padding).replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(base64);
  return Uint8Array.from(raw, character => character.charCodeAt(0));
}

async function subscribeToPush(registration) {
  const keyResponse = await fetch(API + "/api/push/public-key", { credentials: "include" });
  if (!keyResponse.ok) return;
  const { enabled, public_key: publicKey } = await keyResponse.json();
  if (!enabled || !publicKey) return;

  let subscription = await registration.pushManager.getSubscription();
  if (!subscription) {
    subscription = await registration.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: decodeApplicationServerKey(publicKey),
    });
  }
  const response = await fetch(API + "/api/push/subscribe", {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(subscription.toJSON()),
  });
  if (!response.ok) throw new Error("Не удалось сохранить подписку на уведомления");
}

export function initializePushNotifications(authenticated) {
  if (!authenticated || initializationStarted || !("serviceWorker" in navigator) ||
      !("PushManager" in window) || !("Notification" in window)) return;
  const standalone = window.matchMedia("(display-mode: standalone)").matches ||
    window.navigator.standalone === true;
  if (!standalone) return;

  initializationStarted = true;
  const start = async requestPermission => {
    try {
      if (Notification.permission === "default" && requestPermission) {
        const permission = await Notification.requestPermission();
        if (permission !== "granted") return;
      }
      if (Notification.permission !== "granted") return;
      const registration = await navigator.serviceWorker.register("/sw.js");
      await subscribeToPush(registration);
    } catch (error) {
      console.warn("UknowApp push setup failed:", error);
    }
  };

  if (Notification.permission === "granted") {
    void start(false);
  } else if (Notification.permission === "default") {
    const requestOnInteraction = () => void start(true);
    window.addEventListener("pointerdown", requestOnInteraction, { once: true, passive: true });
    window.addEventListener("keydown", requestOnInteraction, { once: true });
  }
}
