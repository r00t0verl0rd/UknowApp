import ChatsView from "./ChatsView.jsx";

export default function StudentWorkspace(options) {
  return () => options.context.page === "boards"
    ? (
        <section class="boards-placeholder" aria-label="Доски">
          <img src="/logo-main.svg" alt="" />
          <h1>Раздел в разработке.</h1>
          <p>Здесь появится удобное пространство для совместной работы, материалов и визуальных задач.</p>
        </section>
      )
    : options.context.page === "chats"
      ? <ChatsView context={options.context} />
      : null;
}
