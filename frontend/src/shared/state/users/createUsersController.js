import { createMemo, merge } from "solid-js";
import { createUserEditorState } from "./createUserEditorState.js";
import { createUserActionState } from "./createUserActionState.js";
import {
  createAssignment,
  unassignStudent as unassignStudentApi,
  createUser,
  createUserConnectionCode,
  deleteUser,
  disconnectUserTelegram,
  resetUserTelegramTopic,
  telegramId, maxId,
  issuePanelAccessCode,
  updateUser,
} from "../../../features/users/services/usersApi.js";
export function createUsersController(options) {
  const editor = createUserEditorState();
  const actions = createUserActionState();
  const allTeachers = createMemo(() =>
    options.directory.users
      .filter((user) => user.role === "teacher")
      .sort(
        (a, b) =>
          a.full_name.localeCompare(b.full_name, "ru", {
            sensitivity: "base",
          }) || String(a.id).localeCompare(String(b.id)),
      ),
  );
  const allStudents = createMemo(() => options.directory.users.filter((user) => user.role === "student"));
  const studentsByTeacherId = createMemo(
    () =>
      new Map(
        (options.directory.overview?.teachers || []).map((teacher) => [teacher.id, teacher.students || []]),
      ),
  );
  const visibleUsers = createMemo(() =>
    options.directory.users
      .filter((user) =>
        (user.full_name + " " + [telegramId(user), maxId(user)].join(" "))
          .toLowerCase()
          .includes(options.directory.search.toLowerCase()),
      )
      .sort((a, b) => {
        if (options.directory.userSort === "teachers")
          return (
            (a.role === "teacher" ? 0 : 1) - (b.role === "teacher" ? 0 : 1) ||
            a.full_name.localeCompare(b.full_name, "ru")
          );
        if (options.directory.userSort === "students")
          return (
            (a.role === "student" ? 0 : 1) - (b.role === "student" ? 0 : 1) ||
            a.full_name.localeCompare(b.full_name, "ru")
          );
        return (
          a.full_name.localeCompare(b.full_name, "ru", {
            sensitivity: "base",
          }) * (options.directory.userSort === "name-desc" ? -1 : 1)
        );
      }),
  );
  const assignedStudentIds = createMemo(
    () =>
      new Set(
        (options.directory.overview?.teachers || []).flatMap((teacher) =>
          teacher.students.map((student) => student.id),
        ),
      ),
  );
  const unassignedStudents = createMemo(() =>
    allStudents().filter((student) => !assignedStudentIds().has(student.id)),
  );
  const openCreate = (defaultRole = "student") => {
    editor.setIssuedCredential(null);
    options.setModal({
      mode: "create",
      id: null,
    });
    editor.setName("");
    editor.setPanelLogin("");
    editor.setRole(defaultRole);
    editor.setAdditionalInfo("");
    editor.setTelegramId("");
    editor.setMaxId("");
  };
  const openEdit = (user, focusTelegram = false) => {
    options.setModal({
      mode: "edit",
      focusTelegram,
      original: user,
      id: user.id,
    });
    editor.setName(user.full_name);
    editor.setPanelLogin(user.web_username || user.full_name);
    editor.setRole(user.role);
    editor.setAdditionalInfo(user.additional_info || "");
    editor.setMaxId(String(maxId(user) || ""));
    editor.setTelegramId(telegramId(user) ? String(telegramId(user)) : "");
  };
  const saveUser = async (event) => {
    event.preventDefault();
    const modal = options.modal;
    if (!modal || editor.savingUser) return;
    editor.setSavingUser(true);
    const body = {
      full_name: editor.name.trim(),
      role: editor.role,
      messenger_accounts: [
        ["telegram", editor.telegramId, telegramId], ["max", editor.maxId, maxId],
      ].filter(([, value, existing]) => value.trim() !== String(existing(modal.original || {}) || ""))
        .map(([platform, value]) => ({ platform, external_user_id: value.trim() || null })),
    };
    if (editor.role === "student") body.additional_info = editor.additionalInfo.trim();
    if (editor.role === "teacher" || editor.role === "student")
      body.web_username = (editor.panelLogin || editor.name).trim();
    try {
      const saved =
        modal.mode === "create"
          ? await createUser(options.request, body)
          : await updateUser(options.request, modal.id, body);
      options.setModal(null);
      await options.refresh();
      if (saved.issued_access_code) {
        editor.setIssuedCredential({
          full_name: saved.full_name,
          username: saved.web_username || saved.full_name,
          code: saved.issued_access_code,
          role: saved.role,
        });
      } else {
        options.notify(modal.mode === "create" ? "Участник добавлен" : "Изменения сохранены");
      }
    } catch (error) {
      options.setError(error.message || "Не удалось сохранить профиль");
    } finally {
      editor.setSavingUser(false);
    }
  };
  const regeneratePanelAccessCode = async () => {
    if (!options.modal || options.modal.mode !== "edit" || !["teacher", "student"].includes(editor.role))
      return;
    editor.setSavingUser(true);
    try {
      const issued = await issuePanelAccessCode(options.request, options.modal.id);
      editor.setIssuedCredential({
        full_name: issued.full_name,
        username: issued.web_username || issued.full_name,
        code: issued.issued_access_code,
        role: issued.role,
      });
      void options.refresh();
    } catch (error) {
      options.setError(error.message || "Не удалось создать новый код доступа");
    } finally {
      editor.setSavingUser(false);
    }
  };
  const removeUser = (user) => actions.setDeleteCandidate(user);
  const confirmRemoveUser = async () => {
    const user = actions.deleteCandidate;
    if (!user || actions.deletingUser) return;
    actions.setDeletingUser(true);
    try {
      await deleteUser(options.request, user.id);
      if (
        options.selectedChat?.type !== "personal" &&
        options.selectedChat &&
        (options.selectedChat.teacher?.id === user.id || options.selectedChat.student?.id === user.id)
      ) {
        options.setSelectedChat(null);
        options.setMessages([]);
      }
      actions.setDeleteCandidate(null);
      if (options.modal?.mode === "edit" && options.modal.id === user.id) options.setModal(null);
      await options.refresh();
      options.notify("Пользователь удалён");
    } catch (error) {
      options.setError(error.message);
    } finally {
      actions.setDeletingUser(false);
    }
  };
  const assign = async (event) => {
    event.preventDefault();
    try {
      await createAssignment(options.request, editor.teacherId, editor.studentId);
      options.setModal(null);
      await options.refresh();
      options.notify("Ученик назначен учителю");
    } catch (error) {
      options.setError(error.message);
    }
  };
  const requestUnassignStudent = (student) => actions.setUnassignCandidate(student);
  const confirmUnassignStudent = async () => {
    const student = actions.unassignCandidate;
    if (!student || actions.unassigningStudent) return;
    actions.setUnassigningStudent(true);
    try {
      await unassignStudentApi(options.request, student.id);
      actions.setUnassignCandidate(null);
      await options.refresh();
      options.notify("Ученик теперь в списке «Без учителя». История переписки сохранена");
    } catch (error) {
      options.setError(error.message || "Не удалось отвязать ученика");
    } finally {
      actions.setUnassigningStudent(false);
    }
  };
  const disconnectTelegram = (user, topicOnly = false, platform = "telegram") => actions.setDisconnectCandidate({ ...user, topicOnly, platform });
  const confirmDisconnectTelegram = async () => {
    const user = actions.disconnectCandidate;
    if (!user || actions.disconnectingTelegram) return;
    actions.setDisconnectingTelegram(true);
    try {
      await (user.topicOnly ? resetUserTelegramTopic : disconnectUserTelegram)(options.request, user.id, user.platform);
      actions.setDisconnectCandidate(null);
      await options.refresh();
      options.notify(user.topicOnly ? "Тема Telegram сброшена. Личный чат сохранён" :
        (user.platform === "max" ? "MAX" : "Telegram") + " отключён. Переписка сохранена в UknowApp");
    } catch (error) {
      options.setError(error.message);
    } finally {
      actions.setDisconnectingTelegram(false);
    }
  };
  const makeCode = async (user) => {
    const confirmed = window.confirm(
      `Выдать новый единый код для «${user.full_name}»?\n\n` +
      "Код используется для входа в веб-панель и подключения Telegram и MAX. " +
      "Старый код сразу перестанет работать, а участнику потребуется войти заново. " +
      "Передайте ему новый код после выдачи.",
    );
    if (!confirmed) return;
    try {
      const result = await createUserConnectionCode(options.request, user.id);
      options.setModal(null);
      editor.setCode({
        ...result,
        full_name: user.full_name,
      });
    } catch (error) {
      options.setError(error.message);
    }
  };
  return merge(options.directory, editor, actions, {
    get allTeachers() {
      return allTeachers();
    },
    get allStudents() {
      return allStudents();
    },
    get studentsByTeacherId() {
      return studentsByTeacherId();
    },
    get visibleUsers() {
      return visibleUsers();
    },
    get unassignedStudents() {
      return unassignedStudents();
    },
    openCreate,
    openEdit,
    saveUser,
    regeneratePanelAccessCode,
    removeUser,
    confirmRemoveUser,
    assign,
    requestUnassignStudent,
    confirmUnassignStudent,
    disconnectTelegram,
    confirmDisconnectTelegram,
    makeCode,
  });
}
