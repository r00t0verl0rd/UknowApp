import ChatsView from "./ChatsView.jsx";

export default function StudentWorkspace(options) {
  return () => (options.context.page === "chats" ? <ChatsView context={options.context} /> : null);
}
