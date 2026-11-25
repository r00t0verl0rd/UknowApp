// Session-only LRU. Never persist private chat history or attachment bytes.
export function createConversationCache({
  createImage = () => document.createElement("img"),
  now = () => Date.now(),
  maxChats = 12,
  maxMessages = 1200,
  historyTtl = 10 * 60 * 1000,
  maxIdleImages = 48,
  maxIdleBytes = 48 * 1024 * 1024,
} = {}) {
  let account = null;
  let allowed = new Set();
  const histories = new Map();
  // Keep the actual image node, not a second download or a second decoded bitmap.
  // Only the visible dialog owns mounted nodes; idle nodes are bounded by count and pixels.
  const images = new Map();
  const imageKey = (chatKey, messageId) => chatKey + ":" + messageId;
  function dropImage(key, entry, revoke = false) {
    if (images.get(key) === entry) images.delete(key);
    if (!entry.active || revoke) entry.image.removeAttribute("src");
  }
  function removeChat(chatKey) {
    histories.delete(chatKey);
    for (const [key, entry] of images) {
      if (entry.chatKey === chatKey) dropImage(key, entry, true);
    }
  }
  function setScope(nextAccount, chatKeys) {
    const nextAllowed = new Set(nextAccount == null ? [] : chatKeys);
    if (account !== nextAccount) {
      histories.clear();
      for (const [key, entry] of images) dropImage(key, entry, true);
      account = nextAccount;
    }
    for (const key of histories.keys()) {
      if (!nextAllowed.has(key)) histories.delete(key);
    }
    for (const [key, entry] of images) {
      if (!nextAllowed.has(entry.chatKey)) dropImage(key, entry, true);
    }
    allowed = nextAllowed;
  }
  function saveHistory(chatKey, messages, olderCursor) {
    if (account == null || !allowed.has(chatKey) || !Array.isArray(messages)) return;
    histories.delete(chatKey);
    if (messages.length > maxMessages) return;
    histories.set(chatKey, { messages, olderCursor, at: now() });
    while (histories.size > maxChats) histories.delete(histories.keys().next().value);
  }
  function getHistory(chatKey) {
    const entry = histories.get(chatKey);
    if (!entry || !allowed.has(chatKey)) return null;
    histories.delete(chatKey);
    if (now() - entry.at > historyTtl) return null;
    histories.set(chatKey, entry);
    return entry;
  }
  function removeMessage(chatKey, messageId) {
    const history = histories.get(chatKey);
    if (history) {
      history.messages = history.messages.filter(row => String(row.id) !== String(messageId));
    }
    const key = imageKey(chatKey, messageId);
    const entry = images.get(key);
    if (entry) dropImage(key, entry, true);
  }
  function clearInactiveHistories(activeKey) {
    for (const key of histories.keys()) {
      if (key !== activeKey) histories.delete(key);
    }
  }
  function imageBytes(entry) {
    const { image, estimatedBytes } = entry;
    return image.naturalWidth && image.naturalHeight
      ? image.naturalWidth * image.naturalHeight * 4
      : estimatedBytes;
  }
  function trimImages() {
    const idle = [...images].filter(([, entry]) => !entry.active);
    let bytes = idle.reduce((total, [, entry]) => total + imageBytes(entry), 0);
    let count = idle.length;
    for (const [key, entry] of idle) {
      if (count <= maxIdleImages && bytes <= maxIdleBytes) break;
      bytes -= imageBytes(entry);
      count--;
      dropImage(key, entry);
    }
  }
  function acquireImage(chatKey, messageId, src, width, height) {
    const key = imageKey(chatKey, messageId);
    const existing = images.get(key);
    if (existing && !existing.active && existing.src === src) {
      existing.active = true;
      images.delete(key);
      images.set(key, existing);
      return existing;
    }
    const image = createImage();
    const entry = {
      image, chatKey, src, key, active: true,
      estimatedBytes: width > 0 && height > 0 ? width * height * 4 : 4 * 1024 * 1024,
    };
    // Duplicate mounted instances must not steal an image from another owner.
    if (account != null && allowed.has(chatKey) && !existing?.active) {
      if (existing) dropImage(key, existing);
      images.set(key, entry);
      image.addEventListener("load", trimImages);
      image.addEventListener("error", () => {
        if (!entry.active && images.get(key) === entry) dropImage(key, entry);
      });
    }
    return entry;
  }
  function releaseImage(entry) {
    entry.active = false;
    if (images.get(entry.key) !== entry) return;
    const image = entry.image;
    if (!image.getAttribute("src") || (image.complete && !image.naturalWidth)) {
      dropImage(entry.key, entry);
      return;
    }
    images.delete(entry.key);
    images.set(entry.key, entry);
    trimImages();
  }
  return { setScope, getHistory, saveHistory, removeChat, removeMessage,
    clearInactiveHistories, acquireImage, releaseImage };
}
