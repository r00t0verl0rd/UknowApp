import Activity from "lucide-react/dist/esm/icons/activity.js";
import Layers from "lucide-react/dist/esm/icons/layers.js";
import MessageCircle from "lucide-react/dist/esm/icons/message-circle.js";
import Users from "lucide-react/dist/esm/icons/users.js";
import Info from "lucide-react/dist/esm/icons/info.js";
import Bell from "lucide-react/dist/esm/icons/bell.js";
import BellOff from "lucide-react/dist/esm/icons/bell-off.js";
import AdminWorkspace from "./AdminWorkspace.jsx";
import TeacherWorkspace from "./TeacherWorkspace.jsx";
import StudentWorkspace from "./StudentWorkspace.jsx";

export const workspaceRegistry = Object.freeze({
  admin: {
    Component: AdminWorkspace,
    label: "Управление школой",
    pages: ["graph", "chats", "users", "boards", "additional"],
    navigation: [
      { page: "graph", label: "Структура", icon: Activity },
      { page: "chats", label: "Диалоги", icon: MessageCircle },
      { page: "users", label: "Пользователи", icon: Users },
      { page: "boards", label: "Доски", icon: Layers },
      { page: "additional", label: "Дополнительно", icon: Info },
    ],
  },
  teacher: {
    Component: TeacherWorkspace,
    label: "Личный кабинет учителя",
    pages: ["chats", "graph"],
    navigation: [
      { page: "chats", label: "Диалоги", icon: MessageCircle },
      { page: "graph", label: "Структура", icon: Activity },
    ],
  },
  student: {
    Component: StudentWorkspace,
    label: "Личный кабинет ученика",
    pages: ["chats"],
    navigation: [{ page: "chats", label: "Диалоги", icon: MessageCircle }],
  },
});

export const workspaceIcons = Object.freeze({ PushOn: Bell, PushOff: BellOff });
