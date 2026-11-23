import ChatsPage from "./ChatsPage.jsx";
import ChatDialogs from "./components/ChatDialogs.jsx";
import { createChatsController } from "./state/createChatsController.js";
export default function ChatsModule(options) {
  const state = createChatsController({
    get auth() {
      return options.auth;
    },
    request: options.request,
    get profile() {
      return options.profile;
    },
    chatState: options.chatState,
    personalState: options.personalState,
    setPage: options.setPage,
    setError: options.setError,
    setModal: options.setModal,
    notify: options.notify,
  });
  return (
    <>
      <ChatsPage
        setError={options.setError}
        profile={options.profile}
        inboxLoading={options.inboxLoading}
        chatSection={options.personalState.chatSection}
        setChatSection={options.personalState.setChatSection}
        personalChats={options.personalState.personalChats}
        setSelectedChat={options.chatState.setSelectedChat}
        setMessages={options.chatState.setMessages}
        chatFilter={options.chatState.chatFilter}
        setChatFilter={options.chatState.setChatFilter}
        openCreatePersonalChat={state.openCreatePersonalChat}
        chatSearch={options.chatState.chatSearch}
        setChatSearch={options.chatState.setChatSearch}
        visibleChats={state.visibleChats}
        openChat={state.openChat}
        selectedChat={options.chatState.selectedChat}
        draft={options.chatState.draft}
        setDraft={options.chatState.setDraft}
        messageFilter={options.chatState.messageFilter}
        setMessageFilter={options.chatState.setMessageFilter}
        messagesViewportRef={options.chatState.messagesViewportRef}
        visibleMessages={state.visibleMessages}
        messages={options.chatState.messages}
        messagesLoading={options.chatState.messagesLoading}
        setDeleteMessageCandidate={state.setDeleteMessageCandidate}
        attachment={options.chatState.attachment}
        setAttachment={options.chatState.setAttachment}
        sendChatMessage={state.sendChatMessage}
      />
      <ChatDialogs
        modal={options.modal}
        setModal={options.setModal}
        users={options.users}
        createPersonalChat={state.createPersonalChat}
        creating={state.creating}
        deleteMessageCandidate={state.deleteMessageCandidate}
        selectedChat={options.chatState.selectedChat}
        deletingMessage={state.deletingMessage}
        setDeleteMessageCandidate={state.setDeleteMessageCandidate}
        confirmDeleteMessage={state.confirmDeleteMessage}
      />
    </>
  );
}
