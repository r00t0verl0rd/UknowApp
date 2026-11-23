import ChatsModule from "../features/conversations/index.js";

// Страница переписок для любой роли; роли отличаются только списком участников для новых диалогов.
export default function ChatsView(options) {
  return (
    <ChatsModule
      auth={options.context.auth}
      profile={options.context.profile}
      request={options.context.request}
      chatState={options.context.chatState}
      personalState={options.context.personalState}
      inboxLoading={options.context.inboxLoading}
      users={options.users ?? []}
      modal={options.context.modal}
      setPage={options.context.setPage}
      setError={options.context.setError}
      setModal={options.context.setModal}
      notify={options.context.notify}
    />
  );
}
