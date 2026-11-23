import { lazy, Loading, Switch, Match } from "solid-js";
const ChatsView = lazy(() => import("./ChatsView.jsx"));
const UsersModule = lazy(() => import("../features/users/index.js"));
const AdministrationModule = lazy(() => import("../features/administration/index.js"));
export default function AdminWorkspace(props) {
  return (
    <Loading fallback={null}>
      <AdminPage {...props} />
    </Loading>
  );
}
function AdminPage(options) {
  return (
    <Switch>
      <Match when={options.context.page === "boards"}>
        <section class="boards-placeholder" aria-label="Доски">
          <img src="/logo-main.svg" alt="" />
          <h1>Раздел в разработке.</h1>
          <p>Здесь появится удобное пространство для совместной работы, материалов и визуальных задач.</p>
        </section>
      </Match>
      <Match when={["graph", "users"].includes(options.context.page)}>
        <UsersModule
          page={options.context.page}
          directory={options.context.directory}
          request={options.context.request}
          adminDataLoading={options.context.adminDataLoading}
          refresh={options.context.refresh}
          notify={options.context.notify}
          setError={options.context.setError}
          selectedChat={options.context.chatState.selectedChat}
          setSelectedChat={options.context.chatState.setSelectedChat}
          setMessages={options.context.chatState.setMessages}
          modal={options.context.modal}
          setModal={options.context.setModal}
        />
      </Match>
      <Match when={options.context.page === "additional"}>
        <AdministrationModule
          page={options.context.page}
          auth={options.context.auth}
          profile={options.context.profile}
          request={options.context.request}
          refresh={options.context.refresh}
          notify={options.context.notify}
          setError={options.context.setError}
          setSelectedChat={options.context.chatState.setSelectedChat}
          setMessages={options.context.chatState.setMessages}
          restoreFlow={options.context.restoreFlow}
        />
      </Match>
      <Match when={options.context.page === "chats"}>
        <ChatsView context={options.context} users={options.context.directory.users} />
      </Match>
    </Switch>
  );
}
