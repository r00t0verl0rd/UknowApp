import ArrowLeft from "lucide-react/dist/esm/icons/arrow-left.js";
import Check from "lucide-react/dist/esm/icons/check.js";
import ChevronRight from "lucide-react/dist/esm/icons/chevron-right.js";
import MessageCircle from "lucide-react/dist/esm/icons/message-circle.js";
import Paperclip from "lucide-react/dist/esm/icons/paperclip.js";
import Plus from "lucide-react/dist/esm/icons/plus.js";
import Search from "lucide-react/dist/esm/icons/search.js";
import X from "lucide-react/dist/esm/icons/x.js";
import MessageBubble from "./components/MessageBubble.jsx";

export default function ChatsPage({ profile, chatSection, setChatSection, personalChats, setSelectedChat, setMessages, chatFilter, setChatFilter, openCreatePersonalChat, chatSearch, setChatSearch, visibleChats, openChat, selectedChat, setPage, draft, setDraft, messageFilter, setMessageFilter, messagesViewportRef, visibleMessages, messages, setDeleteMessageCandidate, attachment, setAttachment, sendChatMessage }) {
  return (
    <>
      <div className={"chat-layout" + (selectedChat ? " chat-layout-conversation-open" : " chat-layout-list-open")}><div className="chat-list">{profile?.role === "admin" && <div className="chat-filter-segment admin-chat-sections" role="group" aria-label="Раздел диалогов"><button type="button" className={chatSection === "participants" ? "active" : ""} onClick={() => { setChatSection("participants"); setSelectedChat(null); setMessages([]); }}>Чаты участников</button><button type="button" className={chatSection === "personal" ? "active" : ""} onClick={() => { setChatSection("personal"); setChatFilter("all"); setSelectedChat(null); setMessages([]); }}>Личные{personalChats.some(chat => Number(chat.unread_count) > 0) && <span className="unread-badge">{personalChats.reduce((sum, chat) => sum + (Number(chat.unread_count) || 0), 0) > 99 ? "99+" : personalChats.reduce((sum, chat) => sum + (Number(chat.unread_count) || 0), 0)}</span>}</button></div>}{profile?.role === "admin" && chatSection === "personal" && <button type="button" className="btn outline personal-chat-create" onClick={openCreatePersonalChat}><Plus size={15}/>Создать диалог</button>}{profile?.role !== "student" && <>
                  <div className="chat-search-control">
                    <Search size={17}/>
                    <input aria-label="Поиск по имени" placeholder="Поиск по имени" value={chatSearch} onChange={e => setChatSearch(e.target.value)}/>
                    {chatSearch && <button type="button" onClick={() => setChatSearch("")} aria-label="Очистить поиск"><X size={14}/></button>}
                  </div>
                  {(profile?.role === "teacher" || (profile?.role === "admin" && chatSection === "personal")) && <div className="chat-filter-segment" role="group" aria-label="Фильтр диалогов">
                    <button type="button" className={chatFilter === "all" ? "active" : ""} aria-pressed={chatFilter === "all"} onClick={() => setChatFilter("all")}>
                      <MessageCircle size={14}/>{profile?.role === "admin" ? "Все личные" : "Все диалоги"}
                    </button>
                    <button type="button" className={chatFilter === "unread" ? "active" : ""} aria-pressed={chatFilter === "unread"} onClick={() => setChatFilter("unread")}>
                      <Check size={14}/>Непрочитанные
                    </button>
                  </div>}
                </>}
                <div className="chat-items-scroll">{visibleChats.map(chat => {
                  const personal = chat.type === "personal";
                  const showMessageCount = profile?.role === "admin" && chatSection === "participants" && !personal;
                  const unreadCount = Number(chat.unread_count) || 0;
                  const displayedCount = showMessageCount ? Number(chat.message_count) || 0 : unreadCount;
                  return <button key={chat.id} className={"chat-item " + (selectedChat?.id === chat.id && (selectedChat?.type === "personal") === personal ? "selected " : "") + (unreadCount > 0 && !showMessageCount ? "has-unread" : "")} onClick={() => openChat(chat)}>
                    <div className="chat-item-heading">
                      <div className={"chat-item-participants" + (profile?.role === "student" ? " is-student-view" : "")}>
                        {personal ? <span>{chat.title}</span> : <>{profile?.role === "admin" && <span>{chat.teacher.full_name}</span>}<span>{profile?.role === "student" ? chat.teacher.full_name : chat.student.full_name}</span>{profile?.role === "student" && <small>Учитель</small>}</>}
                        {personal && <small>Личный диалог</small>}
                      </div>
                      {(showMessageCount || unreadCount > 0) && <span className={showMessageCount ? "message-count-badge" : "unread-badge"} title={showMessageCount ? "Всего сообщений" : "Непрочитанные сообщения"} aria-label={showMessageCount ? displayedCount + " сообщений всего" : displayedCount + " непрочитанных сообщений"}>{displayedCount > 99 ? "99+" : displayedCount}</span>}
                    </div>
                  </button>;
                })}{!visibleChats.length && <div className="empty-state">{profile?.role === "admin" && chatSection === "personal" ? "Личных диалогов пока нет" : profile?.role === "student" ? "Пока нет активной переписки с учителем" : profile?.role === "admin" ? "Активных диалогов участников нет" : "По выбранному фильтру ничего не найдено"}</div>}</div></div>
                <div className="chat-detail">{selectedChat ? <>
                  <div className="chat-head"><button type="button" className="mobile-chat-back" onClick={() => { setSelectedChat(null); setMessages([]); }} aria-label="Назад к списку диалогов"><ArrowLeft size={19}/><span>Диалоги</span></button><div className="chat-head-person"><b>{selectedChat.type === "personal" ? selectedChat.title : profile?.role === "student" ? selectedChat.teacher.full_name : selectedChat.student.full_name}</b>{selectedChat.type === "personal" && <small>Личный диалог · только UknowApp</small>}{selectedChat.type !== "personal" && profile?.role === "admin" && <small>{selectedChat.teacher.full_name}</small>}{selectedChat.type !== "personal" && profile?.role === "student" && <small>Ваш учитель</small>}</div><div className="chat-head-tools"><select aria-label="Фильтр сообщений" value={messageFilter} onChange={e => setMessageFilter(e.target.value)}><option value="all">Все сообщения</option><option value="media">Все вложения</option><option value="audio">Аудио</option><option value="photos">Фото</option><option value="files">Файлы и видео</option></select>{selectedChat.type !== "personal" && selectedChat.status !== "active" && <span className="role-tag">Закрыта</span>}</div></div>
                  <div className="messages" ref={messagesViewportRef}>{visibleMessages.map(message => <MessageBubble message={message} key={message.id} onDelete={setDeleteMessageCandidate} viewerRole={profile?.role} />)}{!messages.length && <div className="empty-state">Сообщений пока нет</div>}{!!messages.length && !visibleMessages.length && <div className="empty-state">Нет сообщений этого типа</div>}</div>
                  {(selectedChat.type === "personal" || selectedChat.status === "active") && <form className="chat-composer" onSubmit={sendChatMessage}>
                    <textarea value={draft} onChange={e => setDraft(e.target.value)} onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); e.currentTarget.form?.requestSubmit(); } }} placeholder={selectedChat.type === "personal" ? "Личное сообщение…" : profile?.role === "admin" ? "Сообщение от администратора обеим сторонам…" : profile?.role === "student" ? "Сообщение учителю…" : "Ответить ученику…"} rows={2} maxLength={4000}/>
                    <div className="composer-footer">
                      <div className="composer-tools">
                        {selectedChat.type !== "personal" && <label className="attach-control"><Paperclip size={16}/> Прикрепить файл<input type="file" accept="image/*,audio/*,video/*,.pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.txt,.zip" onChange={e => setAttachment(e.target.files?.[0] || null)}/></label>}
                        {attachment && <span className="selected-file">{attachment.name}<button type="button" onClick={() => setAttachment(null)} aria-label="Убрать файл"><X size={14}/></button></span>}
                      </div>
                      <button className="btn primary composer-send" disabled={!draft.trim() && !attachment}>Отправить <ChevronRight size={16}/></button>
                    </div>
                  </form>}
                </> : <div className="empty-state">{profile?.role === "student" ? "Ваша переписка с учителем появится здесь" : "Выберите ученика слева"}</div>}</div>
              </div>
            </>}
    </>
    </>
  );
}
