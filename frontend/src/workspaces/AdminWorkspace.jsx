import BoardsPage from "../features/boards/index.js";
import UsersModule from "../features/users/index.js";
import ChatsModule from "../features/conversations/index.js";
import AdministrationModule from "../features/administration/index.js";

export default function AdminWorkspace({ context }) {
  const { page, auth, profile, request, refresh, notify, setError, modal, setModal,
    setPage, chatState, personalState, directory } = context;

  switch (page) {
    case "graph":
    case "users":
      return <UsersModule page={page} directory={directory} request={request}
        refresh={refresh} notify={notify} setError={setError}
        selectedChat={chatState.selectedChat} setSelectedChat={chatState.setSelectedChat}
        setMessages={chatState.setMessages} modal={modal} setModal={setModal}/>;
    case "boards":
      return <BoardsPage />;
    case "additional":
      return <AdministrationModule page={page} auth={auth} profile={profile} request={request}
        refresh={refresh} notify={notify} setError={setError}
        setSelectedChat={chatState.setSelectedChat} setMessages={chatState.setMessages}/>;
    case "chats":
      return <ChatsModule key="admin" page={page} auth={auth} profile={profile} request={request}
        chatState={chatState} personalState={personalState} users={directory.users}
        error={context.error} modal={modal} setPage={setPage} setError={setError}
        setModal={setModal} notify={notify}/>;
    default:
      return null;
  }
}
