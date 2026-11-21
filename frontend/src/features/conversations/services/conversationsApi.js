const API = import.meta.env.VITE_API_BASE_URL || "";

export function getChatMessages(request, chat, afterId = 0) {
  const base = chat.type === "personal" ? "/api/panel/personal-conversations/" : "/api/panel/conversations/";
  const query = afterId > 0 ? "?after_id=" + afterId : "";
  return request(base + chat.id + "/messages" + query);
}

export function getChatSummary(request, chat) {
  const base = chat.type === "personal" ? "/api/panel/personal-conversations/" : "/api/panel/conversations/";
  return request(base + chat.id + "/summary");
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

export function sendPersonalMessage(request, chatId, text) {
  return request("/api/panel/personal-conversations/" + chatId + "/messages", {
    method: "POST",
    body: JSON.stringify({ text }),
  });
}

export function sendConversationText(request, chatId, text) {
  return request("/api/panel/conversations/" + chatId + "/messages", {
    method: "POST",
    body: JSON.stringify({ text }),
  });
}

export async function sendConversationAttachment(chatId, file, text) {
  const form = new FormData();
  form.append("file", file);
  form.append("text", text);
  const response = await fetch(API + "/api/panel/conversations/" + chatId + "/attachments", {
    method: "POST",
    credentials: "include",
    body: form,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || "Не удалось отправить файл");
  return data;
}
