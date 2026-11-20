import ChatsModule from "../features/conversations/index.js";

export default function TeacherWorkspace({ context }) {
  const { page, auth, profile, request, chatState, personalState, setPage,
    setError, modal, setModal, notify, error } = context;

  if (page === "graph") return <div className="graph-panel" />;
  if (page !== "chats") return null;
  return <ChatsModule key="teacher" page={page} auth={auth} profile={profile} request={request}
    chatState={chatState} personalState={personalState} users={[]} error={error} modal={modal}
    setPage={setPage} setError={setError} setModal={setModal} notify={notify}/>;
}
