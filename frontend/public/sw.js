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
    if (await isConversationVisible(payload)) return;
    await self.registration.showNotification(payload.title || "UknowApp", {
      body: payload.body || "Новое сообщение",
      icon: "/logo.png",
      badge: "/favicon.svg",
      tag: payload.tag || "uknowapp-message",
      data: { url: payload.url || "/" },
      renotify: true,
    });
  })());
});

self.addEventListener("notificationclick", event => {
  event.notification.close();
  const target = new URL(event.notification.data?.url || "/", self.location.origin).href;
  event.waitUntil((async () => {
    const windows = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    for (const client of windows) {
      if (new URL(client.url).origin === self.location.origin) {
        await client.navigate(target);
        return client.focus();
      }
    }
    return self.clients.openWindow(target);
  })());
});
