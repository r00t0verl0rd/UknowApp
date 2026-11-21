import { useCallback, useEffect, useMemo } from "react";
import { useUserEditorState } from "./useUserEditorState.js";
import { useUserActionState } from "./useUserActionState.js";
import { createAssignment, unassignStudent as unassignStudentApi, createUser, createUserConnectionCode, deleteUser, disconnectUserTelegram, issuePanelAccessCode, updateUser } from "../../../features/users/services/usersApi.js";

export function useUsersController({
  request, refresh, notify, setError, selectedChat, setSelectedChat,
  setMessages, modal, setModal, directory,
}) {
  const editor = useUserEditorState();
  const actions = useUserActionState();
  const {
    users, setUsers, overview, setOverview, search, setSearch,
    userSort, setUserSort, userInfo, setUserInfo,
  } = directory;

  useEffect(() => {
    if (userInfo === null) return undefined;
    const closeOnOutsideClick = event => {
      if (!event.target.closest?.(".user-info-wrap")) setUserInfo(null);
    };
    const closeOnEscape = event => {
      if (event.key === "Escape") setUserInfo(null);
    };
    document.addEventListener("pointerdown", closeOnOutsideClick);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOnOutsideClick);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [userInfo, setUserInfo]);
  const {
    issuedCredential, setIssuedCredential, savingUser, setSavingUser,
    name, setName, panelLogin, setPanelLogin, role, setRole,
    additionalInfo, setAdditionalInfo, telegramId, setTelegramId,
    teacherId, setTeacherId, studentId, setStudentId, code, setCode,
  } = editor;
  const {
    deleteCandidate, setDeleteCandidate, deletingUser, setDeletingUser,
    disconnectCandidate, setDisconnectCandidate, disconnectingTelegram,
    unassignCandidate, setUnassignCandidate, unassigningStudent, setUnassigningStudent,
    setDisconnectingTelegram,
  } = actions;

  const allTeachers = useMemo(() => users.filter(user => user.role === "teacher").sort((a, b) => a.full_name.localeCompare(b.full_name, "ru", { sensitivity: "base" }) || String(a.id).localeCompare(String(b.id))), [users]);
  const allStudents = useMemo(() => users.filter(user => user.role === "student"), [users]);
  const studentsByTeacherId = useMemo(
    () => new Map((overview?.teachers || []).map(teacher => [teacher.id, teacher.students || []])),
    [overview],
  );
  const visibleUsers = useMemo(() => users
    .filter(user => (user.full_name + " " + (user.telegram_id || "")).toLowerCase().includes(search.toLowerCase()))
    .sort((a, b) => {
      if (userSort === "teachers") return (a.role === "teacher" ? 0 : 1) - (b.role === "teacher" ? 0 : 1) || a.full_name.localeCompare(b.full_name, "ru");
      if (userSort === "students") return (a.role === "student" ? 0 : 1) - (b.role === "student" ? 0 : 1) || a.full_name.localeCompare(b.full_name, "ru");
      return a.full_name.localeCompare(b.full_name, "ru", { sensitivity: "base" }) * (userSort === "name-desc" ? -1 : 1);
    }), [users, search, userSort]);
  const assignedStudentIds = useMemo(
    () => new Set((overview?.teachers || []).flatMap(teacher => teacher.students.map(student => student.id))),
    [overview],
  );
  const unassignedStudents = useMemo(
    () => allStudents.filter(student => !assignedStudentIds.has(student.id)),
    [allStudents, assignedStudentIds],
  );

  const openCreate = useCallback((defaultRole = "student") => {
    setIssuedCredential(null);
    setModal({ mode: "create", id: null });
    setName("");
    setPanelLogin("");
    setRole(defaultRole);
    setAdditionalInfo("");
    setTelegramId("");
    setError("");
  }, [setIssuedCredential, setModal, setName, setPanelLogin, setRole, setAdditionalInfo, setTelegramId, setError]);

  const openEdit = useCallback(user => {
    setModal({ mode: "edit", id: user.id });
    setName(user.full_name);
    setPanelLogin(user.web_username || user.full_name);
    setRole(user.role);
    setAdditionalInfo(user.additional_info || "");
    setTelegramId(user.telegram_id ? String(user.telegram_id) : "");
    setError("");
  }, [setModal, setName, setPanelLogin, setRole, setAdditionalInfo, setTelegramId, setError]);

  const saveUser = useCallback(async event => {
    event.preventDefault();
    setSavingUser(true);
    setError("");
    const body = {
      full_name: name.trim(), role,
      telegram_id: telegramId.trim() ? Number(telegramId) : null,
    };
    if (role === "student") body.additional_info = additionalInfo.trim();
    if (role === "teacher" || role === "student") body.web_username = (panelLogin || name).trim();
    try {
      const saved = modal.mode === "create"
        ? await createUser(request, body)
        : await updateUser(request, modal.id, body);
      setModal(null);
      await refresh();
      if (saved.issued_access_code) {
        setIssuedCredential({
          full_name: saved.full_name,
          username: saved.web_username || saved.full_name,
          code: saved.issued_access_code,
          role: saved.role,
        });
      } else {
        notify(modal.mode === "create" ? "Участник добавлен" : "Изменения сохранены");
      }
    } catch (error) {
      setError(error.message || "Не удалось сохранить профиль");
    } finally {
      setSavingUser(false);
    }
  }, [request, refresh, notify, setError, name, role, telegramId, additionalInfo, panelLogin, modal, setModal, setSavingUser, setIssuedCredential]);

  const regeneratePanelAccessCode = useCallback(async () => {
    if (!modal || modal.mode !== "edit" || !["teacher", "student"].includes(role)) return;
    setSavingUser(true);
    setError("");
    try {
      const issued = await issuePanelAccessCode(request, modal.id);
      setIssuedCredential({
        full_name: issued.full_name,
        username: issued.web_username || issued.full_name,
        code: issued.issued_access_code,
        role: issued.role,
      });
      void refresh();
    } catch (error) {
      setError(error.message || "Не удалось создать новый код доступа");
    } finally {
      setSavingUser(false);
    }
  }, [modal, role, setSavingUser, setError, request, setIssuedCredential, refresh]);

  const removeUser = useCallback(user => setDeleteCandidate(user), [setDeleteCandidate]);

  const confirmRemoveUser = useCallback(async () => {
    const user = deleteCandidate;
    if (!user || deletingUser) return;
    setDeletingUser(true);
    setError("");
    try {
      await deleteUser(request, user.id);
      if (selectedChat?.type !== "personal" && selectedChat
        && (selectedChat.teacher?.id === user.id || selectedChat.student?.id === user.id)) {
        setSelectedChat(null);
        setMessages([]);
      }
      setDeleteCandidate(null);
      if (modal?.mode === "edit" && modal.id === user.id) setModal(null);
      await refresh();
      notify("Пользователь удалён");
    } catch (error) {
      setError(error.message);
    } finally {
      setDeletingUser(false);
    }
  }, [deleteCandidate, deletingUser, setDeletingUser, setError, request, selectedChat, setSelectedChat, setMessages, setDeleteCandidate, modal, setModal, refresh, notify]);

  const assign = useCallback(async event => {
    event.preventDefault();
    try {
      await createAssignment(request, teacherId, studentId);
      setModal(null);
      await refresh();
      notify("Ученик назначен учителю");
    } catch (error) {
      setError(error.message);
    }
  }, [request, teacherId, studentId, setModal, refresh, notify, setError]);

  const requestUnassignStudent = useCallback(student => setUnassignCandidate(student), [setUnassignCandidate]);

  const confirmUnassignStudent = useCallback(async () => {
    const student = unassignCandidate;
    if (!student || unassigningStudent) return;
    setUnassigningStudent(true);
    setError("");
    try {
      await unassignStudentApi(request, student.id);
      setUnassignCandidate(null);
      await refresh();
      notify("Ученик отвязан от учителя");
    } catch (error) {
      setError(error.message || "Не удалось отвязать ученика");
    } finally {
      setUnassigningStudent(false);
    }
  }, [unassignCandidate, unassigningStudent, setUnassigningStudent, setError, request, setUnassignCandidate, refresh, notify]);

  const disconnectTelegram = useCallback(user => setDisconnectCandidate(user), [setDisconnectCandidate]);

  const confirmDisconnectTelegram = useCallback(async () => {
    const user = disconnectCandidate;
    if (!user || disconnectingTelegram) return;
    setDisconnectingTelegram(true);
    setError("");
    try {
      await disconnectUserTelegram(request, user.id);
      setDisconnectCandidate(null);
      await refresh();
      notify("Telegram отключён");
    } catch (error) {
      setError(error.message);
    } finally {
      setDisconnectingTelegram(false);
    }
  }, [disconnectCandidate, disconnectingTelegram, setDisconnectingTelegram, setError, request, setDisconnectCandidate, refresh, notify]);

  const makeCode = useCallback(async user => {
    try {
      const result = await createUserConnectionCode(request, user.id);
      setCode({ ...result, full_name: user.full_name });
    } catch (error) {
      setError(error.message);
    }
  }, [request, setCode, setError]);

  return {
    ...directory, ...editor, ...actions,
    allTeachers, allStudents, studentsByTeacherId, visibleUsers, unassignedStudents,
    openCreate, openEdit, saveUser, regeneratePanelAccessCode, removeUser,
    confirmRemoveUser, assign, requestUnassignStudent, unassignCandidate, setUnassignCandidate,
    unassigningStudent, confirmUnassignStudent, disconnectTelegram,
    confirmDisconnectTelegram, makeCode,
  };
}
