import { For, Show } from "solid-js";
import { createSignal, createEffect } from "solid-js";
import {
  IconArrowLeft as ArrowLeft,
  IconMessageCircle as MessageCircle,
  IconEye as Eye,
  IconPaperclip as Paperclip,
  IconPlus as Plus,
  IconSearch as Search,
  IconSend as Send,
  IconTrash2 as Trash2,
  IconX as X,
} from "../../shared/components/Icons.jsx";
import { isUnreadIncoming } from "./services/messageState.js";
import MessageBubble from "./components/MessageBubble.jsx";
import { MESSAGE_DAY_MS, parseMessageDate } from "./services/formatMessageTime.js";
import EmptyState from "../../shared/components/EmptyState.jsx";
import CountBadge from "../../shared/components/CountBadge.jsx";
import IconButton from "../../shared/components/IconButton.jsx";
import ToolbarSelect from "../../shared/components/ToolbarSelect.jsx";
import AutoFitText from "./components/AutoFitText.jsx";
// Names and the arrow remain on one line; shrinking is limited to tight space.
function ParticipantHeading(props) {
  const title = () => props.student + " ↔ " + props.teacher;
  return (
    <b class="participant-dialog-title" title={title()} aria-label={title()}>
      <AutoFitText text={title()} baseSize={15} mobileSize={14} minSize={11}
        class="participant-heading-fit">
        <span data-chat-name-role="student">{props.student}</span>
        <span class="participant-dialog-arrow" aria-hidden="true">↔</span>
        <span data-chat-name-role="teacher">{props.teacher}</span>
      </AutoFitText>
    </b>
  );
}

export default function ChatsPage(options) {
  const [messageNowMs, setMessageNowMs] = createSignal(Date.now());

  createEffect(
    () => [options.selectedChat?.id, options.selectedChat?.type, options.profile?.role, options.visibleMessages, options.positionReady],
    () => {
      const chat = options.selectedChat;
      const viewport = options.messagesViewportRef.current;
      const role = options.profile?.role;
      if (!options.positionReady || !chat || !viewport || !role || (role === "admin" && chat.type !== "personal")) return;
      const unread = new Set(options.visibleMessages
        .filter(message => isUnreadIncoming(message, chat, role))
        .map(message => Number(message.id))
        .filter(id => Number.isSafeInteger(id) && id > 0));
      if (!unread.size) return;

      const messageId = element => Number(element.dataset.viewAnchor.slice("message:".length));
      const visible = new Set();
      let retry;
      let disposed = false;
      const report = () => {
        if (!visible.size || document.visibilityState !== "visible" || !document.hasFocus()) return;
        clearTimeout(retry);
        Promise.resolve(options.acknowledgeVisible(chat, [...visible])).catch(() => {
          if (!disposed) retry = setTimeout(report, 2000);
        });
      };
      const observer = new IntersectionObserver(entries => {
        for (const entry of entries) {
          const id = messageId(entry.target);
          if (entry.isIntersecting && entry.intersectionRect.height > 0) visible.add(id);
          else visible.delete(id);
        }
        report();
      });
      for (const element of viewport.querySelectorAll('[data-view-anchor^="message:"]')) {
        if (unread.has(messageId(element))) observer.observe(element);
      }
      window.addEventListener("focus", report);
      document.addEventListener("visibilitychange", report);
      return () => {
        disposed = true;
        clearTimeout(retry);
        observer.disconnect();
        window.removeEventListener("focus", report);
        document.removeEventListener("visibilitychange", report);
      };
    },
  );

  // Один таймер обновляет даты сообщений при достижении 24 часов.
  createEffect(
    () => [options.visibleMessages, messageNowMs()],
    () => {
      let nextBoundary = Infinity;
      for (const message of options.visibleMessages) {
        const sentAt = parseMessageDate(message.created_at);
        if (sentAt === null) continue;
        const boundary = sentAt + MESSAGE_DAY_MS;
        if (boundary > messageNowMs() && boundary < nextBoundary) {
          nextBoundary = boundary;
        }
      }
      if (nextBoundary === Infinity) return undefined;
      const timeout = window.setTimeout(
        () => setMessageNowMs(Date.now()),
        Math.max(1, nextBoundary - Date.now() + 10),
      );
      return () => window.clearTimeout(timeout);
    },
  );
  function titleRole(chat) {
    if (chat.type === "personal") return options.profile?.role === "admin" ? chat.participant?.role : "admin";
    return options.profile?.role === "student" ? "teacher" : "student";
  }
  const unreadPersonalCount = () =>
    options.personalChats.reduce((total, chat) => total + (Number(chat.unread_count) || 0), 0);
  const selectedChatKey = () => {
    const chat = options.selectedChat;
    return chat ? (chat.type === "personal" ? "personal:" : "conversation:") + chat.id : null;
  };
  return (
    <>
      <section class="teacher-branch chat-list workspace-panel">
        <div class="chat-list-actions workspace-control-row">
          {options.profile?.permissions?.includes("dialogs.observe") && (
            <div
              class="chat-section-tabs ui-toolbar-control ui-toolbar-segmented"
              role="group"
              aria-label="Тип диалогов"
            >
              <button
                type="button"
                class={options.chatSection === "participants" ? "chat-section-tab ui-toolbar-tab is-current" : "chat-section-tab ui-toolbar-tab"}
                aria-pressed={options.chatSection === "participants" ? "true" : "false"}
                title="Чаты участников"
                onClick={() => {
                  options.setChatSection("participants");
                  options.setSelectedChat(null);
                  options.setMessages([]);
                }}
              >
                Участники
              </button>
              <button
                type="button"
                class={options.chatSection === "personal" ? "chat-section-tab ui-toolbar-tab is-current" : "chat-section-tab ui-toolbar-tab"}
                aria-pressed={options.chatSection === "personal" ? "true" : "false"}
                title="Личные диалоги"
                onClick={() => {
                  options.setChatSection("personal");
                  options.setChatFilter("all");
                  options.setSelectedChat(null);
                  options.setMessages([]);
                }}
              >
                Личные
                <CountBadge
                  value={unreadPersonalCount()}
                  unread={unreadPersonalCount() > 0}
                  label="непрочитанных личных сообщений"
                  hideWhenZero
                />
              </button>
            </div>
          )}
          {options.profile?.role === "admin" && options.chatSection === "personal" && (
            <IconButton
              class="personal-chat-create ui-toolbar-icon"
              onClick={options.openCreatePersonalChat}
              aria-label="Новый диалог"
              title="Новый личный диалог"
            >
              <Plus size={17} />
            </IconButton>
          )}
        </div>
        {options.profile?.role !== "student" && (
          <div class="chat-list-filters workspace-control-row">
            <label class="search workspace-search ui-toolbar-control">
              <Search size={16} />
              <input
                aria-label="Поиск по имени"
                placeholder="Поиск по имени"
                value={options.chatSearch}
                onInput={(event) => options.setChatSearch(event.target.value)}
              />
              {options.chatSearch && (
                <IconButton
                  size="compact"
                  onClick={() => options.setChatSearch("")}
                  aria-label="Очистить поиск"
                >
                  <X size={14} />
                </IconButton>
              )}
            </label>
            {(options.profile?.role === "teacher" ||
              (options.profile?.role === "admin" && options.chatSection === "personal")) && (
              <label class="chat-filter">
                <ToolbarSelect
                  class="chat-filter-field"
                  aria-label="Фильтр диалогов"
                  value={options.chatFilter}
                  onChange={(event) => options.setChatFilter(event.target.value)}
                >
                  <option value="all">
                    {options.profile?.role === "admin" ? "Все личные" : "Все диалоги"}
                  </option>
                  <option value="unread">Непрочитанные</option>
                </ToolbarSelect>
              </label>
            )}
          </div>
        )}

        <div class="chat-items" role="region" aria-label="Список диалогов">
          <For each={options.visibleChats} keyed={(chat) => (chat.type === "personal" ? "personal:" : "conversation:") + chat.id}>
            {(chat) => {
              const row = () => chat();
              const personal = () => row().type === "personal";
              const showMessageCount = () =>
                options.profile?.role === "admin" && options.chatSection === "participants" && !personal();
              const unreadCount = () => Number(row().unread_count) || 0;
              const displayedCount = () =>
                showMessageCount() ? Number(row().message_count) || 0 : unreadCount();
              const isSelected = () =>
                options.selectedChat?.id === row().id &&
                (options.selectedChat?.type === "personal") === personal();
              const title = () =>
                personal()
                  ? row().title
                  : options.profile?.role === "student"
                    ? row().teacher.full_name
                    : options.profile?.role === "admin"
                      ? row().teacher.full_name
                      : row().student.full_name;
              const secondary = () =>
                !personal() && options.profile?.role === "admin"
                  ? row().student.full_name
                  : !personal() && options.profile?.role === "student"
                    ? "Учитель"
                    : "";
              return (
                <button
                  type="button"
                  class={
                    "student-card chat-item" +
                    (isSelected() ? " selected" : "") +
                    (unreadCount() > 0 && !showMessageCount() ? " has-unread" : "")
                  }
                  aria-pressed={isSelected()}
                  data-view-anchor={"chat:" + (personal() ? "personal:" : "conversation:") + row().id}
                  onClick={() => options.openChat(row())}
                >
                  <div class="person-main">
                    <div class="avatar chat-avatar">
                      {showMessageCount() ? <Eye size={19} aria-hidden="true" /> : <MessageCircle size={17} aria-hidden="true" />}
                    </div>
                    <div class={"person-info" + (showMessageCount() ? " participant-chat-names" : "")}>
                      {showMessageCount() ? (
                        <>
                          <b><AutoFitText text={row().teacher.full_name} baseSize={14} minSize={12}>
                            <span data-chat-name-role="teacher">{row().teacher.full_name}</span>
                          </AutoFitText></b>
                          <b><AutoFitText text={row().student.full_name} baseSize={14} minSize={12}>
                            <span data-chat-name-role="student">{row().student.full_name}</span>
                          </AutoFitText></b>
                        </>
                      ) : (
                        <>
                          <b><AutoFitText text={title()} baseSize={14} minSize={12}>
                            <span data-chat-name-role={titleRole(row())}>{title()}</span>
                          </AutoFitText></b>
                          {secondary() && <small>{secondary()}</small>}
                        </>
                      )}
                    </div>
                  </div>
                  {(showMessageCount() || unreadCount() > 0) && (
                    <CountBadge
                      value={displayedCount()}
                      unread={!showMessageCount() && unreadCount() > 0}
                      title={showMessageCount() ? "Всего сообщений" : "Непрочитанные сообщения"}
                      label={showMessageCount() ? "сообщений всего" : "непрочитанных сообщений"}
                    />
                  )}
                </button>
              );
            }}
          </For>
          {!options.inboxLoading && !options.visibleChats.length && (
            <EmptyState>
              {options.profile?.role === "admin" && options.chatSection === "personal"
                ? "Личных диалогов пока нет"
                : options.profile?.role === "student"
                  ? "Пока нет активной переписки с учителем"
                  : options.profile?.role === "admin"
                    ? "Активных диалогов участников нет"
                    : "По выбранному фильтру ничего не найдено"}
            </EmptyState>
          )}
        </div>
      </section>

      <section class="teacher-branch chat-detail">
        <Show
          when={selectedChatKey()}
          keyed
          fallback={
            <EmptyState>
              {options.profile?.role === "student"
                ? "Ваша переписка с учителем появится здесь"
                : "Выберите диалог из списка"}
            </EmptyState>
          }
        >
          {() => (
            <>
            <header class="chat-head">
              <button
                type="button"
                class="btn small mobile-chat-back"
                onClick={() => {
                  options.setSelectedChat(null);
                  options.setMessages([]);
                }}
                aria-label="Назад к списку диалогов"
              >
                <ArrowLeft size={17} />
                <span>Диалоги</span>
              </button>
              <div class="chat-head-person">
                {options.selectedChat.type !== "personal" && options.profile?.role === "admin" ? (
                  <ParticipantHeading
                    student={options.selectedChat.student.full_name}
                    teacher={options.selectedChat.teacher.full_name}
                  />
                ) : (
                  <b data-chat-name-role={titleRole(options.selectedChat)}>
                    <AutoFitText text={options.selectedChat.type === "personal"
                      ? options.selectedChat.title
                      : options.profile?.role === "student"
                        ? options.selectedChat.teacher.full_name
                        : options.selectedChat.student.full_name} baseSize={15} mobileSize={14} minSize={12}>
                      {options.selectedChat.type === "personal"
                      ? options.selectedChat.title
                      : options.profile?.role === "student"
                        ? options.selectedChat.teacher.full_name
                        : options.selectedChat.student.full_name}
                    </AutoFitText>
                  </b>
                )}
                {options.selectedChat.type !== "personal" && options.profile?.role === "student" && (
                  <small>Ваш учитель</small>
                )}
              </div>
              <div class="chat-head-tools">
                <label
                  class="chat-message-filter-control ui-chat-head-action"
                  title={{
                    all: "Все сообщения",
                    media: "Все вложения",
                    audio: "Аудио",
                    photos: "Фото",
                    files: "Файлы и видео",
                  }[options.messageFilter] || "Фильтр сообщений"}
                >
                  <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                    <path d="M4 7h16M7 12h10M10 17h4" />
                  </svg>
                  <ToolbarSelect
                    class="chat-message-filter"
                    aria-label="Фильтр сообщений"
                    value={options.messageFilter}
                    onChange={(event) => options.setMessageFilter(event.target.value)}
                  >
                    <option value="all">Все сообщения</option>
                    <option value="media">Все вложения</option>
                    <option value="audio">Аудио</option>
                    <option value="photos">Фото</option>
                    <option value="files">Файлы и видео</option>
                  </ToolbarSelect>
                </label>
                {options.profile?.role === "admin" && options.selectedChat.type === "personal" && (
                  <IconButton
                    size="large"
                    class="ui-chat-head-action"
                    onClick={() => options.setDeletePersonalChatCandidate(options.selectedChat)}
                    aria-label="Закрыть и удалить личный диалог"
                    title="Закрыть личный диалог и удалить историю у всех"
                  >
                    <Trash2 size={18} />
                  </IconButton>
                )}
                {options.selectedChat.type !== "personal" && options.selectedChat.status !== "active" && (
                  <span class="role-tag">Закрыта</span>
                )}
              </div>
            </header>

            <div
              class="messages"
              style={{ visibility: options.positionReady ? "visible" : "hidden" }}
              aria-busy={!options.positionReady}
              data-view-scroll-key={options.selectedChat
                ? (options.selectedChat.type === "personal" ? "personal:" : "conversation:") + options.selectedChat.id
                : ""}
              ref={(element) => {
                options.messagesViewportRef.current = element;
              }}
            >
              {options.hasOlder && <button type="button" class="btn" disabled={options.loadingOlder}
                onClick={options.loadOlder}>{options.loadingOlder ? "Загружаем…" : "Показать предыдущие сообщения"}</button>}
              <For each={options.visibleMessages} keyed={(message) => message.id}>
                {(message) => (
                  <MessageBubble
                    onError={options.setError}
                    message={message()}
                    cache={options.cache}
                    chatKey={selectedChatKey()}
                    onDelete={options.setDeleteMessageCandidate}
                    viewerRole={options.profile?.role}
                    personalChat={options.selectedChat.type === "personal"}
                    deliveryRecipients={options.selectedChat.type === "personal"
                      ? [options.selectedChat.participant].filter(Boolean)
                      : [options.selectedChat.student, options.selectedChat.teacher].filter(Boolean)}
                    nowMs={messageNowMs()}
                  />
                )}
              </For>
              {!options.messagesLoading && !options.messages.length && (
                <EmptyState>Сообщений пока нет</EmptyState>
              )}
              {!!options.messages.length && !options.visibleMessages.length && (
                <EmptyState>Нет сообщений этого типа</EmptyState>
              )}
            </div>

            <div class="chat-latest-control">
              <Show when={options.positionReady && options.showLatest}>
                <button type="button" class="btn chat-latest-button"
                  onClick={options.scrollToLatest}
                  aria-label="К последнему сообщению" title="К последнему сообщению">
                  <svg viewBox="0 0 24 24" width="20" height="20" fill="none"
                    stroke="currentColor" stroke-width="2" stroke-linecap="round"
                    stroke-linejoin="round" aria-hidden="true">
                    <path d="M12 5v14m-6-6 6 6 6-6" />
                  </svg>
                </button>
              </Show>
            </div>

            {(options.selectedChat.type === "personal" || options.selectedChat.status === "active") && (
              <form class="chat-composer" onSubmit={options.sendChatMessage}>
                <textarea
                  value={options.draft}
                  onInput={(event) => options.setDraft(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" && !event.shiftKey) {
                      event.preventDefault();
                      event.currentTarget.form?.requestSubmit();
                    }
                  }}
                  placeholder={
                    options.selectedChat.type === "personal"
                      ? "Личное сообщение…"
                      : options.profile?.role === "admin"
                        ? "Сообщение ученику и учителю…"
                        : options.profile?.role === "student"
                          ? "Сообщение учителю…"
                          : "Ответить ученику…"
                  }
                  rows={1}
                  maxLength={4000}
                />
                <div class="composer-footer">
                  <div class="composer-tools">
                    <label
                      class="attach-control ui-icon-button"
                      aria-label="Прикрепить файл"
                      title="Прикрепить файл"
                    >
                      <Paperclip size={17} />
                      <input
                        type="file"
                        aria-label="Выбрать файл для сообщения"
                        accept="image/*,audio/*,video/*,.pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.txt,.zip"
                        onInput={(event) => options.setAttachment(event.target.files?.[0] || null)}
                      />
                    </label>
                    {options.attachment && (
                      <span class="selected-file">
                        <span class="selected-file-name">{options.attachment.name}</span>
                        <IconButton
                          size="compact"
                          onClick={() => options.setAttachment(null)}
                          aria-label="Убрать файл"
                        >
                          <X size={14} />
                        </IconButton>
                      </span>
                    )}
                  </div>
                  <button
                    type="submit"
                    class="btn primary composer-send"
                    aria-label="Отправить сообщение"
                    title="Отправить сообщение"
                    disabled={!options.draft.trim() && !options.attachment}
                  >
                    <Send size={16} />
                    <span>Отправить</span>
                  </button>
                </div>
              </form>
            )}
            </>
          )}
        </Show>
      </section>
    </>
  );
}
