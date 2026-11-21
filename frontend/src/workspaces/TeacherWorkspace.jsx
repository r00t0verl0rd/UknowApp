import ChatsModule from "../features/conversations/index.js";

export default function TeacherWorkspace({ context }) {
  const { auth, profile, request, chatState, personalState, setPage,
    setError, modal, setModal, notify, error, inboxLoading } = context;

  return <ChatsModule key="teacher" page="chats" auth={auth} profile={profile} request={request}
    chatState={chatState} personalState={personalState} inboxLoading={inboxLoading} users={[]} error={error} modal={modal}
    setPage={setPage} setError={setError} setModal={setModal} notify={notify}/>;
}
