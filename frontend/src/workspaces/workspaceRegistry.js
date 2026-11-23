import { IconActivity as Activity, IconLayers as Layers, IconMessageCircle as MessageCircle, IconUsers as Users, IconInfo as Info, IconBell as Bell, IconBellOff as BellOff } from "../shared/components/Icons.jsx";
import AdminWorkspace from "./AdminWorkspace.jsx";
import TeacherWorkspace from "./TeacherWorkspace.jsx";
import StudentWorkspace from "./StudentWorkspace.jsx";

// Новые роли добавляются здесь вместе с серверными проверками доступа.
export const workspaceRegistry = Object.freeze({
  admin: {
    Component: AdminWorkspace,
    label: "Управление школой",
    pages: ["graph", "chats", "users", "boards", "additional"],
    navigation: [{
      page: "graph",
      label: "Структура",
      icon: Activity
    }, {
      page: "chats",
      label: "Диалоги",
      icon: MessageCircle
    }, {
      page: "users",
      label: "Пользователи",
      icon: Users
    }, {
      page: "boards",
      label: "Доски",
      icon: Layers
    }, {
      page: "additional",
      label: "Дополнительно",
      icon: Info
    }]
  },
  teacher: {
    Component: TeacherWorkspace,
    label: "Личный кабинет учителя",
    pages: ["graph", "chats", "boards"],
    navigation: [{
      page: "graph",
      label: "Структура",
      icon: Activity
    }, {
      page: "chats",
      label: "Диалоги",
      icon: MessageCircle
    }, { page: "boards", label: "Доски", icon: Layers }]
  },
  student: {
    Component: StudentWorkspace,
    label: "Личный кабинет ученика",
    pages: ["chats", "boards"],
    navigation: [{
      page: "chats",
      label: "Диалоги",
      icon: MessageCircle
    }, { page: "boards", label: "Доски", icon: Layers }]
  }
});
export const workspaceIcons = Object.freeze({
  PushOn: Bell,
  PushOff: BellOff
});

const pagePermission = Object.freeze({
  graph: "structure.view", chats: "dialogs.own", users: "users.manage",
  boards: "boards.view", additional: "school.manage",
});

export function workspaceFor(profile) {
  if (!profile || !Object.hasOwn(workspaceRegistry, profile.role) || !Array.isArray(profile.permissions)) return null;
  const config = workspaceRegistry[profile.role];
  const navigation = config.navigation.filter(({ page }) => profile.permissions.includes(pagePermission[page]));
  return navigation.length ? { ...config, navigation, pages: navigation.map(({ page }) => page) } : null;
}
