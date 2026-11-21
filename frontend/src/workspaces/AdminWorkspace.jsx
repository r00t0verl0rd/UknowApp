import { lazy, Suspense } from "react";
import ChatsModule from "../features/conversations/index.js";

const BoardsPage = lazy(() => import("../features/boards/index.js"));
const UsersModule = lazy(() => import("../features/users/index.js"));
const AdministrationModule = lazy(() => import("../features/administration/index.js"));

export default function AdminWorkspace(props) {
  return (
    <Suspense fallback={<p role="status">Загружаем раздел…</p>}>
      <AdminPage {...props} />
    </Suspense>
  );
}

function AdminPage({ context }) {
  const { page, auth, profile, request, refresh, notify, setError, modal, setModal,
    setPage, chatState, personalState, directory, inboxLoading, adminDataLoading } = context;

  switch (page) {
    case "graph":
    case "users":
      return <UsersModule page={page} directory={directory} request={request} adminDataLoading={adminDataLoading}
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
        chatState={chatState} personalState={personalState} inboxLoading={inboxLoading} users={directory.users}
        error={context.error} modal={modal} setPage={setPage} setError={setError}
        setModal={setModal} notify={notify}/>;
    default:
      return null;
  }
}
