import ChatsPage from "./ChatsPage.jsx";
import ChatDialogs from "./components/ChatDialogs.jsx";
import { createChatsController } from "./state/createChatsController.js";
import { saveViewPreference } from "../../shared/services/viewSession.js";
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
    get inboxLoading() { return options.inboxLoading; },
  });
  const clearSelectedChat = () => {
    state.capturePosition();
    saveViewPreference(options.profile?.id, "chats.active", null);
    options.chatState.setSelectedChat(null);
  };
  return (
    <>
      <ChatsPage
        setError={options.setError}
        profile={options.profile}
        inboxLoading={options.inboxLoading}
        chatSection={options.personalState.chatSection}
        setChatSection={options.personalState.setChatSection}
        personalChats={options.personalState.personalChats}
        setSelectedChat={clearSelectedChat}
        setMessages={options.chatState.setMessages}
        chatFilter={options.chatState.chatFilter}
        setChatFilter={options.chatState.setChatFilter}
        openCreatePersonalChat={state.openCreatePersonalChat}
        chatSearch={options.chatState.chatSearch}
        setChatSearch={options.chatState.setChatSearch}
        visibleChats={state.visibleChats}
        hasOlder={state.hasOlder}
        loadingOlder={state.loadingOlder}
        loadOlder={state.loadOlder}
        openChat={state.openChat}
        selectedChat={options.chatState.selectedChat}
        draft={options.chatState.draft}
        setDraft={options.chatState.setDraft}
        messageFilter={options.chatState.messageFilter}
        setMessageFilter={options.chatState.setMessageFilter}
        messagesViewportRef={options.chatState.messagesViewportRef}
        visibleMessages={state.visibleMessages}
        positionReady={state.positionReady}
        acknowledgeVisible={options.acknowledgeVisible}
        messages={options.chatState.messages}
        messagesLoading={options.chatState.messagesLoading}
        setDeleteMessageCandidate={state.setDeleteMessageCandidate}
        setDeletePersonalChatCandidate={state.setDeletePersonalChatCandidate}
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
        deletePersonalChatCandidate={state.deletePersonalChatCandidate}
        deletingPersonalChat={state.deletingPersonalChat}
        setDeletePersonalChatCandidate={state.setDeletePersonalChatCandidate}
        confirmDeletePersonalChat={state.confirmDeletePersonalChat}
      />
    </>
  );
}
