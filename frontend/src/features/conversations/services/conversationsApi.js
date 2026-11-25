import { apiUrl, request } from "../../../shared/services/api.js";

export const HISTORY_PAGE_SIZE = 50;

export function getChatMessages(request, chat, signal, beforeId, afterId) {
  const base = chat.type === "personal" ? "/api/panel/personal-conversations/" : "/api/panel/conversations/";
  const params = new URLSearchParams({ mark_read: "false", limit: String(HISTORY_PAGE_SIZE) });
  if (beforeId) params.set("before_id", String(beforeId));
  if (afterId != null) {
    params.set("after_id", String(afterId));
    params.set("forward", "true");
  }
  return request(base + chat.id + "/messages?" + params, { signal });
}

export function getChatWindow(request, chat, signal, anchorId) {
  const base = chat.type === "personal" ? "/api/panel/personal-conversations/" : "/api/panel/conversations/";
  const params = new URLSearchParams({ mark_read: "false", limit: String(HISTORY_PAGE_SIZE) });
  if (anchorId) params.set("around_id", String(anchorId));
  else params.set("first_unread", "true");
  return request(base + chat.id + "/messages?" + params, { signal });
}

export async function syncChatState(request, chat, afterId, knownMessageIds) {
  const base = chat.type === "personal" ? "/api/panel/personal-conversations/" : "/api/panel/conversations/";
  const result = { messages: [], updated_messages: [], deleted_message_ids: [] };
  let cursor = Math.max(0, Number(afterId) || 0);
  let start = 0;
  do {
    const batch = await request(base + chat.id + "/sync", {
      method: "POST",
      body: JSON.stringify({ paged: true, mark_read: false, after_id: cursor, known_message_ids: knownMessageIds.slice(start, start + 5000) }),
    });
    for (const message of batch.messages || []) {
      result.messages.push(message);
      cursor = Math.max(cursor, message.id);
    }
    result.updated_messages.push(...(batch.updated_messages || []));
    result.deleted_message_ids.push(...(batch.deleted_message_ids || []));
    result.summary = batch.summary;
    result.has_more = Boolean(batch.has_more && batch.messages?.length);
    start += 5000;
  } while (start < knownMessageIds.length);
  return result;
}


export function acknowledgeChatMessages(request, chat, ids) {
  const base = chat.type === "personal" ? "/api/panel/personal-conversations/" : "/api/panel/conversations/";
  return request(base + chat.id + "/read", {
    method: "POST",
    body: JSON.stringify({ message_ids: ids }),
  });
}

export function createPersonalConversation(request, userId) {
  return request("/api/panel/personal-conversations", {
    method: "POST",
    body: JSON.stringify({ user_id: Number(userId) }),
  });
}

export function deletePersonalConversation(request, conversationId) {
  return request("/api/panel/personal-conversations/" + Number(conversationId), {
    method: "DELETE",
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

export async function sendConversationAttachment(chatId, file, text, clientMessageId, personal = false) {
  const form = new FormData();
  form.append("file", file);
  form.append("text", text);
  if (clientMessageId) form.append("client_message_id", clientMessageId);
  const path = personal ? "/api/panel/personal-conversations/" : "/api/panel/conversations/";
  return request(path + chatId + "/attachments", { method: "POST", body: form });
}

export function messageMediaUrl(messageId, personal = false) {
  return apiUrl((personal ? "/api/panel/personal-messages/" : "/api/panel/messages/") + messageId + "/media");
}
