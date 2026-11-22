import { useEffect, useState } from "react";
import ArrowLeft from "lucide-react/dist/esm/icons/arrow-left.js";
import MessageCircle from "lucide-react/dist/esm/icons/message-circle.js";
import Paperclip from "lucide-react/dist/esm/icons/paperclip.js";
import Plus from "lucide-react/dist/esm/icons/plus.js";
import Search from "lucide-react/dist/esm/icons/search.js";
import Send from "lucide-react/dist/esm/icons/send.js";
import X from "lucide-react/dist/esm/icons/x.js";
import MessageBubble from "./components/MessageBubble.jsx";
import { MESSAGE_DAY_MS, parseMessageDate } from "./services/formatMessageTime.js";
import EmptyState from "../../shared/components/EmptyState.jsx";
import CountBadge from "../../shared/components/CountBadge.jsx";
import IconButton from "../../shared/components/IconButton.jsx";

export default function ChatsPage({
  setError, profile, inboxLoading, chatSection, setChatSection, personalChats, setSelectedChat,
  setMessages, chatFilter, setChatFilter, openCreatePersonalChat, chatSearch,
  setChatSearch, visibleChats, openChat, selectedChat, draft, setDraft,
  messageFilter, setMessageFilter, messagesViewportRef, visibleMessages, messages, messagesLoading,
  setDeleteMessageCandidate, attachment, setAttachment, sendChatMessage,
}) {
  const [messageNowMs, setMessageNowMs] = useState(Date.now);

  // Один таймер обновляет даты сообщений при достижении 24 часов.
  useEffect(() => {
    let nextBoundary = Infinity;
    for (const message of visibleMessages) {
      const sentAt = parseMessageDate(message.created_at);
      if (sentAt === null) continue;
      const boundary = sentAt + MESSAGE_DAY_MS;
      if (boundary > messageNowMs && boundary < nextBoundary) {
        nextBoundary = boundary;
      }
    }
    if (nextBoundary === Infinity) return undefined;
    const timeout = window.setTimeout(
      () => setMessageNowMs(Date.now()),
      Math.max(1, nextBoundary - Date.now() + 10),
    );
    return () => window.clearTimeout(timeout);
  }, [visibleMessages, messageNowMs]);

  const unreadPersonalCount = personalChats.reduce(
    (total, chat) => total + (Number(chat.unread_count) || 0), 0,
  );

  return (
    <>
      <section className="teacher-branch chat-list">
        <div className="chat-list-actions">
          {profile?.role === "admin" && (
            <div className="chat-section-tabs" role="group" aria-label="Тип диалогов">
              <button type="button" className="chat-section-tab"
                aria-pressed={chatSection === "participants"} title="Чаты участников"
                onClick={() => {
                  setChatSection("participants");
                  setSelectedChat(null);
                  setMessages([]);
                }}>
                Участники
              </button>
              <button type="button" className="chat-section-tab"
                aria-pressed={chatSection === "personal"} title="Личные диалоги"
                onClick={() => {
                  setChatSection("personal");
                  setChatFilter("all");
                  setSelectedChat(null);
                  setMessages([]);
                }}>
                Личные
                <CountBadge value={unreadPersonalCount}
                  label="непрочитанных личных сообщений" hideWhenZero />
              </button>
            </div>
          )}
          {profile?.role === "admin" && chatSection === "personal" && (
            <IconButton className="personal-chat-create" onClick={openCreatePersonalChat}
              aria-label="Новый диалог" title="Новый личный диалог">
              <Plus size={17}/>
            </IconButton>
          )}
        </div>
        {profile?.role !== "student" && (
          <div className="chat-list-filters">
            <label className="search workspace-search">
              <Search size={16}/>
              <input aria-label="Поиск по имени" placeholder="Поиск по имени"
                value={chatSearch} onChange={event => setChatSearch(event.target.value)}/>
              {chatSearch && (
                <IconButton size="compact" onClick={() => setChatSearch("")}
                  aria-label="Очистить поиск">
                  <X size={14}/>
                </IconButton>
              )}
            </label>
            {(profile?.role === "teacher" || (profile?.role === "admin" && chatSection === "personal")) && (
              <label className="chat-filter">
                <span>Показать</span>
                <select aria-label="Фильтр диалогов" value={chatFilter}
                  onChange={event => setChatFilter(event.target.value)}>
                  <option value="all">{profile?.role === "admin" ? "Все личные" : "Все диалоги"}</option>
                  <option value="unread">Непрочитанные</option>
                </select>
              </label>
            )}
          </div>
        )}

        <div className="chat-items" role="region" aria-label="Список диалогов">
          {visibleChats.map(chat => {
            const personal = chat.type === "personal";
            const showMessageCount = profile?.role === "admin" && chatSection === "participants" && !personal;
            const unreadCount = Number(chat.unread_count) || 0;
            const displayedCount = showMessageCount ? Number(chat.message_count) || 0 : unreadCount;
            const isSelected = selectedChat?.id === chat.id
              && (selectedChat?.type === "personal") === personal;
            const title = personal
              ? chat.title
              : profile?.role === "student"
                ? chat.teacher.full_name
                : profile?.role === "admin"
                  ? chat.teacher.full_name
                  : chat.student.full_name;
            const secondary = !personal && profile?.role === "admin"
              ? chat.student.full_name
              : !personal && profile?.role === "student"
                ? "Учитель"
                : "";

            return (
              <button key={(personal ? "personal:" : "conversation:") + chat.id} type="button"
                className={"student-card chat-item" + (isSelected ? " selected" : "")
                  + (unreadCount > 0 && !showMessageCount ? " has-unread" : "")}
                aria-pressed={isSelected} onClick={() => openChat(chat)}>
                <div className="person-main">
                  <div className="avatar chat-avatar"><MessageCircle size={17}/></div>
                  <div className={"person-info" + (showMessageCount ? " participant-chat-names" : "")}>
                    {showMessageCount ? (
                      <>
                        <b className="participant-teacher-name">{chat.teacher.full_name}</b>
                        <small className="participant-student-name">{chat.student.full_name}</small>
                      </>
                    ) : (
                      <>
                        <b>{title}</b>
                        {secondary && <small>{secondary}</small>}
                      </>
                    )}
                  </div>
                </div>
                {(showMessageCount || unreadCount > 0) && (
                  <CountBadge
                    value={displayedCount}
                    unread={!showMessageCount && unreadCount > 0}
                    title={showMessageCount ? "Всего сообщений" : "Непрочитанные сообщения"}
                    label={showMessageCount ? "сообщений всего" : "непрочитанных сообщений"}
                  />
                )}
              </button>
            );
          })}
          {!inboxLoading && !visibleChats.length && (
            <EmptyState>
              {profile?.role === "admin" && chatSection === "personal"
                ? "Личных диалогов пока нет"
                : profile?.role === "student"
                  ? "Пока нет активной переписки с учителем"
                  : profile?.role === "admin"
                    ? "Активных диалогов участников нет"
                    : "По выбранному фильтру ничего не найдено"}
            </EmptyState>
          )}
        </div>
      </section>

      <section className="teacher-branch chat-detail">
        {selectedChat ? (
          <>
            <header className="chat-head">
              <button type="button" className="btn small mobile-chat-back"
                onClick={() => {
                  setSelectedChat(null);
                  setMessages([]);
                }}
                aria-label="Назад к списку диалогов">
                <ArrowLeft size={17}/><span>Диалоги</span>
              </button>
              <div className="chat-head-person">
                <b>{selectedChat.type === "personal"
                  ? selectedChat.title
                  : profile?.role === "student"
                    ? selectedChat.teacher.full_name
                    : selectedChat.student.full_name}</b>
                {selectedChat.type !== "personal" && profile?.role === "admin"
                  && <small>{selectedChat.teacher.full_name}</small>}
                {selectedChat.type !== "personal" && profile?.role === "student"
                  && <small>Ваш учитель</small>}
              </div>
              <div className="chat-head-tools">
                <select aria-label="Фильтр сообщений" value={messageFilter}
                  onChange={event => setMessageFilter(event.target.value)}>
                  <option value="all">Все сообщения</option>
                  <option value="media">Все вложения</option>
                  <option value="audio">Аудио</option>
                  <option value="photos">Фото</option>
                  <option value="files">Файлы и видео</option>
                </select>
                {selectedChat.type !== "personal" && selectedChat.status !== "active"
                  && <span className="role-tag">Закрыта</span>}
              </div>
            </header>

            <div className="messages" ref={messagesViewportRef}>
              {visibleMessages.map(message => (
                <MessageBubble onError={setError} message={message} key={message.id}
                  onDelete={setDeleteMessageCandidate} viewerRole={profile?.role}
                  personalChat={selectedChat.type === "personal"} nowMs={messageNowMs}/>
              ))}
              {!messagesLoading && !messages.length && <EmptyState>Сообщений пока нет</EmptyState>}
              {!!messages.length && !visibleMessages.length
                && <EmptyState>Нет сообщений этого типа</EmptyState>}
            </div>

            {(selectedChat.type === "personal" || selectedChat.status === "active") && (
              <form className="chat-composer" onSubmit={sendChatMessage}>
                <textarea value={draft} onChange={event => setDraft(event.target.value)}
                  onKeyDown={event => {
                    if (event.key === "Enter" && !event.shiftKey) {
                      event.preventDefault();
                      event.currentTarget.form?.requestSubmit();
                    }
                  }}
                  placeholder={selectedChat.type === "personal"
                    ? "Личное сообщение…"
                    : profile?.role === "admin"
                      ? "Сообщение…"
                      : profile?.role === "student"
                        ? "Сообщение учителю…"
                        : "Ответить ученику…"}
                  rows={1} maxLength={4000}/>
                <div className="composer-footer">
                  <div className="composer-tools">
                    {selectedChat.type !== "personal" && (
                      <label className="attach-control ui-icon-button" aria-label="Прикрепить файл" title="Прикрепить файл">
                        <Paperclip size={17}/>
                        <input type="file" accept="image/*,audio/*,video/*,.pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.txt,.zip"
                          onChange={event => setAttachment(event.target.files?.[0] || null)}/>
                      </label>
                    )}
                    {attachment && (
                      <span className="selected-file">
                        <span className="selected-file-name">{attachment.name}</span>
                        <IconButton size="compact" onClick={() => setAttachment(null)}
                          aria-label="Убрать файл"><X size={14}/></IconButton>
                      </span>
                    )}
                  </div>
                  <button type="submit" className="btn primary composer-send"
                    aria-label="Отправить сообщение" title="Отправить сообщение"
                    disabled={!draft.trim() && !attachment}>
                    <Send size={16}/><span>Отправить</span>
                  </button>
                </div>
              </form>
            )}
          </>
        ) : (
          <EmptyState>
            {profile?.role === "student"
              ? "Ваша переписка с учителем появится здесь"
              : "Выберите диалог из списка"}
          </EmptyState>
        )}
      </section>
    </>
  );
}
