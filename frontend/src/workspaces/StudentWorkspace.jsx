import ChatsModule from "../features/conversations/index.js";

export default function StudentWorkspace({ context }) {
  const { page, auth, profile, request, chatState, personalState, setPage,
    setError, modal, setModal, notify, inboxLoading } = context;

  if (page !== "chats") return null;
  return <ChatsModule key="student" auth={auth} profile={profile} request={request}
    chatState={chatState} personalState={personalState} inboxLoading={inboxLoading} users={[]} modal={modal}
    setPage={setPage} setError={setError} setModal={setModal} notify={notify}/>;
}
