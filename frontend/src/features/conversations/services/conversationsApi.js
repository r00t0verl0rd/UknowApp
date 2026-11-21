const API = import.meta.env.VITE_API_BASE_URL || "";

export function getChatMessages(request, chat, signal) {
  const base = chat.type === "personal" ? "/api/panel/personal-conversations/" : "/api/panel/conversations/";
  return request(base + chat.id + "/messages", { signal });
}

export function syncChatState(request, chat, afterId, knownMessageIds) {
  const base = chat.type === "personal" ? "/api/panel/personal-conversations/" : "/api/panel/conversations/";
  return request(base + chat.id + "/sync", {
    method: "POST",
    body: JSON.stringify({
      after_id: Math.max(0, Number(afterId) || 0),
      known_message_ids: knownMessageIds.slice(-5000),
    }),
  });
}


export function createPersonalConversation(request, userId) {
  return request("/api/panel/personal-conversations", {
    method: "POST",
    body: JSON.stringify({ user_id: Number(userId) }),
  });
}

export function deleteChatMessage(request, message, personal) {
  const path = personal ? "/api/panel/personal-messages/" : "/api/panel/messages/";
  return request(path + message.id, { method: "DELETE" });
}

export function sendPersonalMessage(request, chatId, text, clientMessageId) {
  return request("/api/panel/personal-conversations/" + chatId + "/messages", {
    method: "POST",
    body: JSON.stringify({
      text,
      ...(clientMessageId ? { client_message_id: clientMessageId } : {}),
    }),
  });
}

export function sendConversationText(request, chatId, text, clientMessageId) {
  return request("/api/panel/conversations/" + chatId + "/messages", {
    method: "POST",
    body: JSON.stringify({
      text,
      ...(clientMessageId ? { client_message_id: clientMessageId } : {}),
    }),
  });
}

export async function sendConversationAttachment(chatId, file, text, clientMessageId) {
  const form = new FormData();
  form.append("file", file);
  form.append("text", text);
  if (clientMessageId) form.append("client_message_id", clientMessageId);
  const response = await fetch(API + "/api/panel/conversations/" + chatId + "/attachments", {
    method: "POST",
    credentials: "include",
    body: form,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || "Не удалось отправить файл");
  return data;
}
