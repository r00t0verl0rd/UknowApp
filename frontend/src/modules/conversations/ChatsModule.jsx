import ChatsPage from "./ChatsPage.jsx";
import ChatDialogs from "./components/ChatDialogs.jsx";
import { useChatsController } from "../../hooks/conversations/useChatsController.js";

export default function ChatsModule({
  page, auth, profile, request, chatState, personalState, users, error, modal,
  setPage, setError, setModal, notify,
}) {
  const state = useChatsController({
    auth, request, profile, chatState, personalState,
    setPage, setError, setModal, notify,
  });

  return <>
    {page === "chats" && <ChatsPage
      profile={profile} chatSection={personalState.chatSection}
      setChatSection={personalState.setChatSection}
      personalChats={personalState.personalChats}
      setSelectedChat={chatState.setSelectedChat} setMessages={chatState.setMessages}
      chatFilter={chatState.chatFilter} setChatFilter={chatState.setChatFilter}
      openCreatePersonalChat={state.openCreatePersonalChat}
      chatSearch={chatState.chatSearch} setChatSearch={chatState.setChatSearch}
      visibleChats={state.visibleChats} openChat={state.openChat}
      selectedChat={chatState.selectedChat} setPage={setPage}
      draft={chatState.draft} setDraft={chatState.setDraft}
      messageFilter={chatState.messageFilter} setMessageFilter={chatState.setMessageFilter}
      messagesViewportRef={chatState.messagesViewportRef}
      visibleMessages={state.visibleMessages} messages={chatState.messages}
      setDeleteMessageCandidate={state.setDeleteMessageCandidate}
      attachment={chatState.attachment} setAttachment={chatState.setAttachment}
      sendChatMessage={state.sendChatMessage}
    />}
    <ChatDialogs
      modal setModal={setModal} users={users}
      createPersonalChat={state.createPersonalChat} error={error} setError={setError}
      deleteMessageCandidate={state.deleteMessageCandidate}
      selectedChat={chatState.selectedChat} deletingMessage={state.deletingMessage}
      setDeleteMessageCandidate={state.setDeleteMessageCandidate}
      confirmDeleteMessage={state.confirmDeleteMessage}
    />
  </>;
}
