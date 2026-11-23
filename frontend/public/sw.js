async function isConversationVisible(payload) {
  if (!payload.conversation_id) return false;
  const windows = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
  for (const client of windows) {
    if (client.visibilityState !== "visible") continue;
    const channel = new MessageChannel();
    const active = await new Promise(resolve => {
      const timeout = setTimeout(() => resolve(false), 250);
      channel.port1.onmessage = event => {
        clearTimeout(timeout);
        resolve(Boolean(event.data?.active));
      };
      client.postMessage({
        type: "UKNOW_CHECK_ACTIVE_CHAT",
        conversationId: payload.conversation_id,
        conversationType: payload.conversation_type || "conversation",
      }, [channel.port2]);
    });
    if (active) return true;
  }
  return false;
}

self.addEventListener("push", event => {
  let payload = {};
  try {
    payload = event.data ? event.data.json() : {};
  } catch {
    payload = { body: event.data ? event.data.text() : "" };
  }
  event.waitUntil((async () => {
    const collection = { personal: "personal-conversations", conversation: "conversations" }[payload.conversation_type];
    if (!collection || !Number.isSafeInteger(payload.conversation_id)) return;
    const access = await fetch(`/api/panel/${collection}/${payload.conversation_id}/summary`, {
      credentials: "same-origin", cache: "no-store",
    }).catch(() => null);
    if (!access?.ok || !access.headers.get("content-type")?.includes("application/json")) return;
    if (await isConversationVisible(payload)) return;
    // Имя отправителя или направление сообщения — единственный заголовок push.
    // Не выводим UknowApp и не дублируем имя отдельной строкой.
    const notificationTitle = typeof payload.body === "string" && payload.body.trim()
      ? payload.body.trim()
      : "Новое сообщение";
    await self.registration.showNotification(notificationTitle, {
      icon: "/logo-big.png",
      badge: "/logo-192.png",
      tag: payload.tag || "uknowapp-message",
      data: { url: payload.url || "/" },
      renotify: true,
    });
  })());
});

self.addEventListener("notificationclick", event => {
  event.notification.close();
  const requested = new URL(event.notification.data?.url || "/", self.location.origin);
  const target = requested.origin === self.location.origin
    ? requested.href : new URL("/", self.location.origin).href;
  event.waitUntil((async () => {
    const windows = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    const appWindows = windows.filter(client => new URL(client.url).origin === self.location.origin);
    // Переходим в нужный диалог и при уже открытом PWA, и при холодном запуске.
    const client = appWindows.find(window => window.focused) || appWindows[0];
    if (client) {
      try {
        const opened = await client.navigate(target);
        if (opened) return opened.focus();
      } catch {
        // Если фоновой вкладкой нельзя управлять, откроем ссылку отдельно.
      }
    }
    return self.clients.openWindow(target);
  })());
});
