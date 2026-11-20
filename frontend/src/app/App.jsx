import { useCallback, useEffect, useLayoutEffect, useMemo, useState } from "react";
import { useAuthState, useChatState, useDirectoryState, useGraphState, useBoardsState, usePersonalChatState, useSettingsState, useUiState, useUserActionState, useUserEditorState } from "../hooks/useAppState.js";
import Activity from "lucide-react/dist/esm/icons/activity.js";
import Layers from "lucide-react/dist/esm/icons/layers.js";
import Check from "lucide-react/dist/esm/icons/check.js";
import LogOut from "lucide-react/dist/esm/icons/log-out.js";
import MessageCircle from "lucide-react/dist/esm/icons/message-circle.js";
import RefreshCw from "lucide-react/dist/esm/icons/refresh-cw.js";
import Trash2 from "lucide-react/dist/esm/icons/trash-2.js";
import Users from "lucide-react/dist/esm/icons/users.js";
import X from "lucide-react/dist/esm/icons/x.js";
import Copy from "lucide-react/dist/esm/icons/copy.js";
import Moon from "lucide-react/dist/esm/icons/moon.js";
import Sun from "lucide-react/dist/esm/icons/sun.js";
import Info from "lucide-react/dist/esm/icons/info.js";
import Bell from "lucide-react/dist/esm/icons/bell.js";
import BellOff from "lucide-react/dist/esm/icons/bell-off.js";
import AdditionalPage from "../modules/administration/AdditionalPage.jsx";
import ChatsPage from "../modules/conversations/ChatsPage.jsx";
import StructurePage from "../modules/graph/StructurePage.jsx";
import BoardsPage from "../modules/graph/BoardsPage.jsx";
import UsersPage from "../modules/users/UsersPage.jsx";
import LoginPage from "../modules/authentication/LoginPage.jsx";
import { detachPushSubscription, disablePushNotifications, enablePushNotifications, getPushNotificationState } from "../modules/notifications/pushNotifications.js";
import { createApiClient } from "../services/api.js";

const API = import.meta.env.VITE_API_BASE_URL || "";

async function copyText(value) {
  try {
    if (window.isSecureContext && navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(value);
      return true;
    }
  } catch {
    // Clipboard API may be unavailable or denied; use the browser fallback.
  }

  const textarea = document.createElement("textarea");
  textarea.value = value;
  textarea.setAttribute("readonly", "");
  textarea.style.position = "fixed";
  textarea.style.opacity = "0";
  textarea.style.pointerEvents = "none";
  document.body.appendChild(textarea);
  textarea.select();
  textarea.setSelectionRange(0, textarea.value.length);
  let copied = false;
  try {
    copied = document.execCommand("copy");
  } catch {
    copied = false;
  }
  textarea.remove();
  return copied;
}

// Главный экран панели: здесь хранятся состояние разделов, данные API и действия пользователя.
export default function App() {
  const {
    auth, setAuth, profile, setProfile, login, setLogin, password, setPassword,
  } = useAuthState();
  const { theme, setTheme } = useSettingsState();
  const { teacherGraph, setTeacherGraph } = useGraphState();
  const { boardObjects, setBoardObjects } = useBoardsState();
  const {
    draft, setDraft, attachment, setAttachment, chats, setChats,
    selectedChat, setSelectedChat, messages, setMessages, messagesViewportRef,
    chatSearch, setChatSearch, chatFilter, setChatFilter,
    messageFilter, setMessageFilter,
  } = useChatState();
  const { personalChats, setPersonalChats, chatSection, setChatSection } = usePersonalChatState();
  const {
    users, setUsers, overview, setOverview, search, setSearch, userSort, setUserSort, userInfo, setUserInfo,
  } = useDirectoryState();
  const {
    issuedCredential, setIssuedCredential, savingUser, setSavingUser,
    name, setName, panelLogin, setPanelLogin, role, setRole, additionalInfo, setAdditionalInfo,
    telegramId, setTelegramId, teacherId, setTeacherId, studentId, setStudentId, code, setCode,
  } = useUserEditorState();
  const {
    deleteCandidate, setDeleteCandidate, deletingUser, setDeletingUser,
    deleteMessageCandidate, setDeleteMessageCandidate, deletingMessage, setDeletingMessage,
    disconnectCandidate, setDisconnectCandidate, disconnectingTelegram, setDisconnectingTelegram,
  } = useUserActionState();
  const {
    page, setPage, error, setError, toast, setToast, modal, setModal,
  } = useUiState();
  const [dataStats, setDataStats] = useState(null);
  const [dataBusy, setDataBusy] = useState(false);
  const [retentionDays, setRetentionDays] = useState("30");
  const [pushState, setPushState] = useState({ supported: false, enabled: false, permission: "default", reason: "Проверяем поддержку уведомлений…" });
  const [pushBusy, setPushBusy] = useState(false);

  useEffect(() => {
    if (userInfo === null) return undefined;
    const closeInfoOnOutsideClick = event => {
      if (!event.target.closest?.(".user-info-wrap")) setUserInfo(null);
    };
    const closeInfoOnEscape = event => {
      if (event.key === "Escape") setUserInfo(null);
    };
    document.addEventListener("pointerdown", closeInfoOnOutsideClick);
    document.addEventListener("keydown", closeInfoOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeInfoOnOutsideClick);
      document.removeEventListener("keydown", closeInfoOnEscape);
    };
  }, [userInfo]);
  // Единая точка HTTP-запросов: добавляет cookie-сессию и приводит ошибки API к понятному сообщению.
  const request = useMemo(() => createApiClient(), []);

  // Загружает актуальные данные панели в зависимости от роли вошедшего пользователя.
  const refresh = useCallback(async () => {
    if (!auth) return;
    setError("");
    try {
      const who = await request("/api/panel/me");
      setProfile(who);

      // Independent panel datasets are fetched together to avoid serial network waits.
      const roleRequest = who.role === "admin"
        ? Promise.all([request("/api/admin/users"), request("/api/admin/overview")])
        : who.role === "teacher" ? request("/api/panel/graph") : Promise.resolve(null);
      const [conversations, roleData, personal] = await Promise.all([
        request("/api/panel/conversations"), roleRequest, request("/api/panel/personal-conversations"),
      ]);
      setChats(conversations); setPersonalChats(personal);
      if (who.role === "admin") {
        const [people, summary] = roleData;
        setUsers(people); setOverview(summary);
      } else if (who.role === "teacher") {
        setTeacherGraph(roleData);
        setBoardObjects([]); setUsers([]); setOverview(null);
      } else {
        setTeacherGraph(null); setBoardObjects([]); setUsers([]); setOverview(null);
        setPage("chats");
        // Keep the inbox visible on entry. Fetching messages marks them read,
        // so only an explicit student click should clear the unread counter.
        setSelectedChat(null);
        setMessages([]);
      }
    } catch (e) {
      setError(e.message);
      if (["учитель", "ученик", "логин", "сессия", "войдите", "учётная запись"].some(term => String(e.message).toLowerCase().includes(term)) || String(e.message).includes("401")) {
        localStorage.removeItem("uknowapp-auth"); sessionStorage.removeItem("uknowapp-auth");
        setAuth("");
        setProfile(null);
      }
    }
  }, [auth, request]);

  useEffect(() => { refresh(); }, [refresh]);

  useEffect(() => {
    if (!auth || profile?.role !== "admin" || page !== "boards") return undefined;
    let active = true;
    request("/api/admin/boards/objects")
      .then(objects => { if (active) setBoardObjects(objects); })
      .catch(error => { if (active) setError(error.message); });
    return () => { active = false; };
  }, [auth, profile?.role, page, request]);

  useEffect(() => {
    if (auth && profile?.role === "teacher") setPage("chats");
  }, [auth, profile?.role, setPage]);

  useEffect(() => {
    if (!auth) {
      setPushState({ supported: false, enabled: false, permission: "default", reason: "Войдите в приложение" });
      return undefined;
    }
    let active = true;
    getPushNotificationState()
      .then(async state => {
        if (state.supported && state.permission === "granted" && !state.enabled) {
          await enablePushNotifications();
          state = await getPushNotificationState();
        }
        if (active) setPushState(state);
      })
      .catch(() => {
        if (active) getPushNotificationState()
          .then(state => { if (active) setPushState(state); })
          .catch(() => {});
      });
    return () => { active = false; };
  }, [auth]);

  useEffect(() => {
    const respondToPush = event => {
      if (event.data?.type !== "UKNOW_CHECK_ACTIVE_CHAT" || !event.ports?.[0]) return;
      event.ports[0].postMessage({
        active: document.visibilityState === "visible"
          && Number(selectedChat?.id) === Number(event.data.conversationId)
          && (selectedChat?.type === "personal" ? "personal" : "conversation") === event.data.conversationType,
      });
    };
    navigator.serviceWorker?.addEventListener("message", respondToPush);
    return () => navigator.serviceWorker?.removeEventListener("message", respondToPush);
  }, [selectedChat?.id, selectedChat?.type]);

  // Notification links restore the exact conversation after the inbox data is loaded.
  useEffect(() => {
    if (!auth || !profile) return;
    const params = new URLSearchParams(window.location.search);
    const conversationId = Number(params.get("openConversation"));
    if (!conversationId) return;
    const personal = params.get("type") === "personal";
    const source = personal ? personalChats : chats;
    const chat = source.find(item => Number(item.id) === conversationId);
    if (!chat) return;
    window.history.replaceState({}, "", window.location.pathname + window.location.hash);
    setPage("chats");
    if (personal) setChatSection("personal");
    setSelectedChat(chat);
    request((personal ? "/api/panel/personal-conversations/" : "/api/panel/conversations/") + chat.id + "/messages")
      .then(setMessages)
      .catch(error => setError(error.message));
  }, [auth, profile, chats, personalChats, request]);

  useEffect(() => {
    localStorage.setItem("uknowapp-theme-v2", theme);
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  // В разделе переписок события SSE сообщают об изменениях; периодический опрос не нужен.
  useEffect(() => {
    if (!auth || page !== "chats") return undefined;
    let active = true;
    let inFlight = false;
    let refreshPending = false;
    let refreshMessagesPending = false;

    const syncChats = async (event, forceMessages = false) => {
      if (!active) return;
      let shouldRefreshMessages = forceMessages;
      if (event) {
        let eventConversationId = null;
        if (event.data) {
          try {
            eventConversationId = Number(JSON.parse(event.data).conversation_id) || null;
          } catch {
            // An empty or malformed event is treated as a general refresh.
          }
        }
        shouldRefreshMessages = !eventConversationId
          || eventConversationId === Number(selectedChat?.id);
      }
      if (inFlight) {
        refreshPending = true;
        refreshMessagesPending ||= Boolean(selectedChat?.id && shouldRefreshMessages);
        return;
      }
      inFlight = true;
      try {
        if (selectedChat?.id && shouldRefreshMessages) {
          const rows = await request((selectedChat.type === "personal" ? "/api/panel/personal-conversations/" : "/api/panel/conversations/") + selectedChat.id + "/messages");
          if (!active) return;
          setMessages(rows);
        }
        // Loading messages marks them read for teachers. Fetch the list after
        // that write so unread counters are correct in the same refresh cycle.
        const [conversations, personal] = await Promise.all([request("/api/panel/conversations"), request("/api/panel/personal-conversations")]);
        if (!active) return;
        setChats(conversations); setPersonalChats(personal);
      } catch {
        // Keep the current conversation visible during brief network interruptions.
      } finally {
        inFlight = false;
        if (refreshPending && active) {
          const reloadMessages = refreshMessagesPending;
          refreshPending = false;
          refreshMessagesPending = false;
          void syncChats(null, reloadMessages);
        }
      }
    };

    // One persistent SSE connection replaces the two-second HTTP polling loop.
    // The server sends an initial update event as soon as the stream is ready.
    const eventSource = new EventSource(API + "/api/panel/events", { withCredentials: true });
    eventSource.addEventListener("update", syncChats);

    const onVisibilityChange = () => {
      if (document.visibilityState === "visible") void syncChats(null, true);
    };
    document.addEventListener("visibilitychange", onVisibilityChange);

    return () => {
      active = false;
      eventSource.close();
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
  }, [auth, page, selectedChat?.id, request]);

  const notify = (message) => { setToast(message); window.setTimeout(() => setToast(""), 2600); };
  const loadDataStats = useCallback(async () => {
    try {
      setDataStats(await request("/api/admin/data/stats"));
    } catch (e) {
      setError(e.message);
    }
  }, [request]);

  useEffect(() => {
    if (auth && profile?.role === "admin" && page === "additional") void loadDataStats();
  }, [auth, profile?.role, page, loadDataStats]);

  async function downloadAdminFile(kind) {
    try {
      const response = await fetch(API + "/api/admin/data/" + kind, { credentials: "include" });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.detail || "Не удалось скачать файл");
      }
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = ({ full: "uknowapp-full-backup.zip", database: "uknowapp-backup.sqlite3", media: "uknowapp-media.zip" })[kind] || "uknowapp-backup";
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      notify("Файл подготовлен к скачиванию");
    } catch (e) {
      setError(e.message);
    }
  }

  async function uploadAdminFile(kind, file) {
    if (!file) return;
    const warning = kind === "full"
      ? "Полностью восстановить UknowApp из этой копии? Текущая база данных и все медиафайлы будут заменены."
      : "Заменить текущую базу данных загруженной копией? Все текущие данные будут перезаписаны.";
    if (!window.confirm(warning)) return;
    setDataBusy(true);
    setError("");
    try {
      const form = new FormData();
      form.append("file", file);
      const response = await fetch(API + "/api/admin/data/" + kind, {
        method: "POST", credentials: "include", body: form,
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || "Не удалось загрузить файл");
      notify(kind === "full" ? "Полная резервная копия восстановлена. Перезагрузите панель." : "База данных восстановлена. Перезагрузите панель.");
      await loadDataStats();
      if (kind === "full" || kind === "database") {
        setSelectedChat(null);
        setMessages([]);
        await refresh();
      }
    } catch (e) {
      setError(e.message);
    } finally {
      setDataBusy(false);
    }
  }

  async function cleanupOldDialogues() {
    const days = Number(retentionDays);
    if (!window.confirm("Удалить переписки и медиафайлы старше " + days + " дней? Действие необратимо.")) return;
    setDataBusy(true);
    setError("");
    try {
      const result = await request("/api/admin/data/dialogues?days=" + days, { method: "DELETE" });
      notify("Удалено сообщений: " + result.deleted_messages + ", личных: " + result.deleted_personal_messages + ", медиафайлов: " + result.deleted_media_files);
      await loadDataStats();
      await refresh();
    } catch (e) {
      setError(e.message);
    } finally {
      setDataBusy(false);
    }
  }

  // Списки участников пересчитываются только при изменении массива пользователей.
  const allTeachers = useMemo(() => users.filter(u => u.role === "teacher"), [users]);
  const allStudents = useMemo(() => users.filter(u => u.role === "student"), [users]);
  const studentsByTeacherId = useMemo(
    () => new Map((overview?.teachers || []).map(teacher => [teacher.id, teacher.students || []])),
    [overview]
  );
  const visibleUsers = useMemo(() => users
    .filter(u => (u.full_name + " " + (u.telegram_id || "")).toLowerCase().includes(search.toLowerCase()))
    .sort((a, b) => {
      if (userSort === "teachers") return (a.role === "teacher" ? 0 : 1) - (b.role === "teacher" ? 0 : 1) || a.full_name.localeCompare(b.full_name, "ru");
      if (userSort === "students") return (a.role === "student" ? 0 : 1) - (b.role === "student" ? 0 : 1) || a.full_name.localeCompare(b.full_name, "ru");
      return a.full_name.localeCompare(b.full_name, "ru", { sensitivity: "base" }) * (userSort === "name-desc" ? -1 : 1);
    }), [users, search, userSort]);
  // Один раз собираем ID уже назначенных учеников, чтобы быстро найти свободных.
  const assignedStudentIds = useMemo(() => new Set((overview?.teachers || []).flatMap(t => t.students.map(s => s.id))), [overview]);
  const unassignedStudents = useMemo(() => allStudents.filter(student => !assignedStudentIds.has(student.id)), [allStudents, assignedStudentIds]);
  const visibleMessages = useMemo(() => messages.filter(message => {
    const kind = message.metadata?.media?.kind || message.content_type;
    if (messageFilter === "all") return true;
    if (messageFilter === "media") return kind !== "text" || Boolean(message.metadata?.media);
    if (messageFilter === "audio") return ["voice", "audio"].includes(kind);
    if (messageFilter === "photos") return kind === "photo";
    if (messageFilter === "files") return ["document", "video", "video_note", "video_sticker", "animation", "animated_sticker", "sticker"].includes(kind);
    return true;
  }), [messages, messageFilter]);

  useLayoutEffect(() => {
    const viewport = messagesViewportRef.current;
    if (!viewport) return undefined;

    const scrollToLatest = () => {
      // New messages are appended at the bottom, directly above the composer.
      viewport.scrollTop = viewport.scrollHeight;
    };

    scrollToLatest();
    const frame = window.requestAnimationFrame(scrollToLatest);

    // Keep the bottom in view when an attachment finishes loading and changes
    // the height of an existing message (for example, audio/video metadata).
    const resizeObserver = typeof ResizeObserver !== "undefined"
      ? new ResizeObserver(scrollToLatest)
      : null;
    const observeMessages = () => {
      if (!resizeObserver) return;
      Array.from(viewport.children).forEach(child => resizeObserver.observe(child));
    };
    observeMessages();

    const mutationObserver = typeof MutationObserver !== "undefined"
      ? new MutationObserver(() => {
          observeMessages();
          scrollToLatest();
        })
      : null;
    mutationObserver?.observe(viewport, { childList: true });

    return () => {
      window.cancelAnimationFrame(frame);
      resizeObserver?.disconnect();
      mutationObserver?.disconnect();
    };
  }, [selectedChat?.id, messageFilter, visibleMessages]);

  const visibleChats = useMemo(() => {
    const query = chatSearch.trim().toLocaleLowerCase("ru");
    const personal = personalChats.filter(chat => (!query || chat.title.toLocaleLowerCase("ru").includes(query)) && (chatFilter === "all" || Number(chat.unread_count || 0) > 0));
    if (profile?.role === "admin" && chatSection === "personal") return personal;
    const regular = profile?.role === "student" ? chats.slice(0, 1) : chats.filter(chat => {
      const names = profile?.role === "admin"
        ? chat.teacher.full_name + " " + chat.student.full_name
        : chat.student.full_name + " " + chat.teacher.full_name;
      const matchesSearch = !query || names.toLocaleLowerCase("ru").includes(query);
      const matchesFilter = profile?.role !== "teacher" || chatFilter === "all" || Number(chat.unread_count || 0) > 0;
      return matchesSearch && matchesFilter;
    });
    return profile?.role === "admin" ? regular : [...regular, ...personal];
  }, [chats, personalChats, chatSection, chatSearch, chatFilter, profile?.role]);

  function toggleTheme() {
    setTheme(current => current === "dark-soft" ? "light" : "dark-soft");
  }

  async function togglePushNotifications() {
    if (pushBusy) return;
    if (!pushState.supported) {
      notify(pushState.reason);
      return;
    }
    if (pushState.permission === "denied") {
      notify("Разрешите уведомления для UknowApp в настройках браузера");
      return;
    }
    setPushBusy(true);
    setError("");
    try {
      if (pushState.enabled) {
        await disablePushNotifications();
        notify("Push-уведомления отключены");
      } else {
        await enablePushNotifications();
        notify("Push-уведомления включены");
      }
      setPushState(await getPushNotificationState());
    } catch (error) {
      setError(error.message || "Не удалось изменить настройки уведомлений");
      try { setPushState(await getPushNotificationState()); } catch { /* Keep the last known state. */ }
    } finally {
      setPushBusy(false);
    }
  }

  const pushButtonTitle = !pushState.supported
    ? pushState.reason
    : pushState.permission === "denied"
      ? "Уведомления запрещены в настройках браузера"
      : pushState.enabled ? "Отключить push-уведомления" : "Включить push-уведомления";

  const pushToggle = (
    <button
      type="button"
      className={`push-toggle${pushState.enabled ? " active" : ""}`}
      onClick={togglePushNotifications}
      disabled={pushBusy}
      title={pushBusy ? "Обновляем настройки уведомлений…" : pushButtonTitle}
      aria-label={pushButtonTitle}
      aria-pressed={pushState.enabled}
    >
      {pushState.enabled ? <Bell size={17}/> : <BellOff size={17}/>}
    </button>
  );

  async function signIn(event) {
    event.preventDefault();
    setError("");

    if (!login.trim()) {
      setError("Введите логин");
      return;
    }
    if (!password) {
      setError("Введите пароль");
      return;
    }

    try {
      const response = await fetch(API + "/api/auth/login", { method: "POST", credentials: "include", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ username: login.trim(), password }) });
      const result = await response.json().catch(() => ({}));
      if (!response.ok) {
        const detail = Array.isArray(result.detail)
          ? result.detail.map(item => item.msg || "Некорректные данные").join("; ")
          : typeof result.detail === "string" ? result.detail : "Не удалось войти";
        throw new Error(detail);
      }
      // Enable push by default immediately after successful login, while the
      // browser still has the login button's user activation.
      setPushBusy(true);
      try {
        await enablePushNotifications();
        setPushState(await getPushNotificationState());
      } catch (pushError) {
        const state = await getPushNotificationState().catch(() => null);
        if (state) setPushState(state);
        if (state?.supported && state.permission !== "denied") {
          notify("Чтобы включить уведомления, нажмите на значок колокольчика");
        }
      } finally {
        setPushBusy(false);
      }
      localStorage.setItem("uknowapp-auth", "1"); sessionStorage.removeItem("uknowapp-auth"); setProfile(result); setPage(["student", "teacher"].includes(result.role) ? "chats" : "graph"); setAuth("1"); setPassword("");
    } catch (e) {
      setError(e.message || "Не удалось войти");
    }
  }

  async function signOut() {
    try {
      await detachPushSubscription();
      await fetch(API + "/api/auth/logout", { method: "POST", credentials: "include" });
    } catch {
      // Clear the local view even when the server is temporarily unreachable.
    }
    localStorage.removeItem("uknowapp-auth"); sessionStorage.removeItem("uknowapp-auth"); setAuth(""); setProfile(null); setTeacherGraph(null); setUsers([]); setOverview(null); setChats([]); setPersonalChats([]); setMessages([]); setSelectedChat(null); setDraft(""); setAttachment(null); setIssuedCredential(null);
  }

  function openCreatePersonalChat() {
    setError("");
    setModal({ mode: "create-personal" });
  }

  function openCreate(defaultRole = "student") {
    setIssuedCredential(null); setModal({ mode: "create", id: null }); setName(""); setPanelLogin(""); setRole(defaultRole); setAdditionalInfo(""); setTelegramId(""); setError("");
  }
  function openEdit(user) {
    setModal({ mode: "edit", id: user.id }); setName(user.full_name); setPanelLogin(user.web_username || user.full_name); setRole(user.role); setAdditionalInfo(user.additional_info || ""); setTelegramId(user.telegram_id ? String(user.telegram_id) : ""); setError("");
  }

  async function saveUser(event) {
    event.preventDefault();
    setSavingUser(true);
    setError("");
    const body = { full_name: name.trim(), role, telegram_id: telegramId.trim() ? Number(telegramId) : null };
    if (role === "student") body.additional_info = additionalInfo.trim();
    if (role === "teacher" || role === "student") body.web_username = (panelLogin || name).trim();
    try {
      const saved = modal.mode === "create"
        ? await request("/api/admin/users", { method: "POST", body: JSON.stringify(body) })
        : await request("/api/admin/users/" + modal.id, { method: "PATCH", body: JSON.stringify(body) });
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
    } catch (e) {
      setError(e.message || "Не удалось сохранить профиль");
    } finally {
      setSavingUser(false);
    }
  }

  async function regeneratePanelAccessCode() {
    if (!modal || modal.mode !== "edit" || !["teacher", "student"].includes(role)) return;
    setSavingUser(true);
    setError("");
    try {
      const issued = await request("/api/admin/users/" + modal.id + "/access-code", { method: "POST" });
      // Show the issued code immediately; refreshing the rest of the panel is non-blocking.
      setIssuedCredential({
        full_name: issued.full_name,
        username: issued.web_username || issued.full_name,
        code: issued.issued_access_code,
        role: issued.role,
      });
      void refresh();
    } catch (e) {
      setError(e.message || "Не удалось создать новый код доступа");
    } finally {
      setSavingUser(false);
    }
  }

  function removeUser(user) {
    setDeleteCandidate(user);
  }

  async function confirmRemoveUser() {
    const user = deleteCandidate;
    if (!user || deletingUser) return;
    setDeletingUser(true);
    setError("");
    try {
      await request("/api/admin/users/" + user.id, { method: "DELETE" });
      if (selectedChat && (selectedChat.teacher.id === user.id || selectedChat.student.id === user.id)) {
        setSelectedChat(null);
        setMessages([]);
      }
      setDeleteCandidate(null);
      if (modal?.mode === "edit" && modal.id === user.id) setModal(null);
      await refresh();
      notify("Пользователь удалён");
    } catch (e) {
      setError(e.message);
    } finally {
      setDeletingUser(false);
    }
  }

  async function assign(event) {
    event.preventDefault();
    try {
      await request("/api/admin/assignments", { method: "POST", body: JSON.stringify({ teacher_id: Number(teacherId), student_id: Number(studentId) }) });
      setModal(null); await refresh(); notify("Ученик назначен учителю");
    } catch (e) { setError(e.message); }
  }

  async function createBoardObject(payload) {
    try {
      await request("/api/admin/boards/objects", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      const objects = await request("/api/admin/boards/objects");
      setBoardObjects(objects);
    } catch (e) {
      setError(e.message);
    }
  }

  async function saveBoardObjectPosition(objectId, x, y) {
    setBoardObjects(current => current.map(item => item.id === objectId ? { ...item, x, y } : item));
    try {
      await request(`/api/admin/boards/objects/${objectId}/position`, {
        method: "PATCH",
        body: JSON.stringify({ x, y }),
      });
    } catch (e) {
      setError(e.message);
    }
  }

  async function deleteBoardObject(objectId) {
    try {
      await request(`/api/admin/boards/objects/${objectId}`, { method: "DELETE" });
      setBoardObjects(current => {
        const removed = new Set([objectId]);
        let changed = true;
        while (changed) {
          changed = false;
          for (const item of current) {
            if (removed.has(item.parent_id) && !removed.has(item.id)) {
              removed.add(item.id);
              changed = true;
            }
          }
        }
        return current.filter(item => !removed.has(item.id));
      });
      notify("Объект удалён");
    } catch (e) {
      setError(e.message);
    }
  }

  async function unassignStudent(student) {
    if (!window.confirm(`Открепить ученика «${student.full_name}» от учителя? История переписки сохранится.`)) return;
    setError("");
    try {
      await request(`/api/admin/assignments/${student.id}`, { method: "DELETE" });
      await refresh();
      notify("Ученик откреплён от учителя");
    } catch (e) {
      setError(e.message);
    }
  }

  function disconnectTelegram(user) {
    setDisconnectCandidate(user);
  }

  async function confirmDisconnectTelegram() {
    const user = disconnectCandidate;
    if (!user || disconnectingTelegram) return;
    setDisconnectingTelegram(true);
    setError("");
    try {
      await request("/api/admin/users/" + user.id + "/disconnect-telegram", { method: "POST" });
      setDisconnectCandidate(null);
      await refresh();
      notify("Telegram отключён");
    } catch (e) { setError(e.message); }
    finally { setDisconnectingTelegram(false); }
  }

  async function makeCode(user) {
    try {
      const result = await request("/api/admin/users/" + user.id + "/connection-code", { method: "POST" });
      setCode({ ...result, full_name: user.full_name }); 
    } catch (e) { setError(e.message); }
  }

  async function openChat(chat) {
    setSelectedChat(chat); setPage("chats"); setDraft(""); setAttachment(null); setMessageFilter("all");
    try {
      const base = chat.type === "personal" ? "/api/panel/personal-conversations/" : "/api/panel/conversations/";
      setMessages(await request(base + chat.id + "/messages"));
      if (chat.type === "personal") setPersonalChats(await request("/api/panel/personal-conversations"));
      else if (profile?.role === "teacher") setChats(await request("/api/panel/conversations"));
    } catch (e) { setError(e.message); }
  }

  async function createPersonalChat(userId) {
    try {
      const chat = await request("/api/panel/personal-conversations", { method: "POST", body: JSON.stringify({ user_id: Number(userId) }) });
      setPersonalChats(await request("/api/panel/personal-conversations"));
      setChatSection("personal");
      setModal(null);
      await openChat(chat);
    } catch (e) { setError(e.message); }
  }

  async function confirmDeleteMessage() {
    const message = deleteMessageCandidate;
    if (!message || deletingMessage) return;
    setDeletingMessage(true);
    setError("");
    try {
      const result = selectedChat?.type === "personal" ? await request("/api/panel/personal-messages/" + message.id, { method: "DELETE" }) : await request("/api/panel/messages/" + message.id, { method: "DELETE" });
      setMessages(current => current.filter(item => item.id !== message.id));
      setDeleteMessageCandidate(null);
      if (selectedChat?.type === "personal") setPersonalChats(await request("/api/panel/personal-conversations"));
      else if (selectedChat) setChats(await request("/api/panel/conversations"));
      if (result.telegram_failed > 0) {
        notify("Удалено из UknowApp. Не удалось удалить копии в Telegram: " + result.telegram_failed + ". Возможно, Telegram уже не разрешает их удаление.");
      } else {
        notify("Сообщение удалено у всех участников");
      }
    } catch (e) {
      setError(e.message || "Не удалось удалить сообщение");
    } finally {
      setDeletingMessage(false);
    }
  }

  async function sendChatMessage(event) {
    event.preventDefault();
    if (!selectedChat || (!draft.trim() && !attachment)) return;
    try {
      let sentMessage;
      if (selectedChat.type === "personal") {
        if (attachment) throw new Error("В личных диалогах доступны только текстовые сообщения");
        sentMessage = await request("/api/panel/personal-conversations/" + selectedChat.id + "/messages", { method: "POST", body: JSON.stringify({ text: draft.trim() }) });
      } else if (attachment) {
        const form = new FormData();
        form.append("file", attachment);
        form.append("text", draft.trim());
        const response = await fetch(API + "/api/panel/conversations/" + selectedChat.id + "/attachments", {
          method: "POST",
          credentials: "include",
          body: form
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.detail || "Не удалось отправить файл");
        sentMessage = data;
      } else {
        sentMessage = await request("/api/panel/conversations/" + selectedChat.id + "/messages", {
          method: "POST", body: JSON.stringify({ text: draft.trim() })
        });
      }
      setDraft(""); setAttachment(null);
      setMessages(await request((selectedChat.type === "personal" ? "/api/panel/personal-conversations/" : "/api/panel/conversations/") + selectedChat.id + "/messages"));
      if (selectedChat.type === "personal") setPersonalChats(await request("/api/panel/personal-conversations"));
      else setChats(await request("/api/panel/conversations"));
      if (selectedChat.type === "personal") notify("Сообщение отправлено внутри UknowApp");
      else if (profile?.role === "admin" && sentMessage?.delivery_status !== "delivered") {
        notify("Сообщение сохранено. Подробности доставки доступны в переписке.");
      } else if (sentMessage?.delivery_status === "delivered" && profile?.role !== "teacher") {
        notify("Сообщение отправлено");
      }
    } catch (e) { setError(e.message); }
  }

  if (!auth) return <LoginPage theme={theme} toggleTheme={toggleTheme} signIn={signIn} login={login} setLogin={setLogin} password={password} setPassword={setPassword} error={error} />;

  return <div className="shell chats-shell">
    <aside className="sidebar">
      <div className="brand"><img src="/logo.png" alt="" /><span>Uknow<span>App</span></span></div>
      <div className="school-label">{profile?.role === "admin" ? "УПРАВЛЕНИЕ ШКОЛОЙ" : profile?.role === "student" ? "ЛИЧНЫЙ КАБИНЕТ УЧЕНИКА" : "РАБОЧЕЕ МЕСТО УЧИТЕЛЯ"}</div>
      <nav>
        {profile?.role === "admin" && <button className={page === "graph" ? "active" : ""} onClick={() => setPage("graph")}><Activity/>Структура</button>}
        {(profile?.role === "admin" || profile?.role === "teacher") && <button className={page === "chats" ? "active" : ""} onClick={() => setPage("chats")}><MessageCircle/>Диалоги</button>}
        {profile?.role === "teacher" && <button className={page === "graph" ? "active" : ""} onClick={() => setPage("graph")}><Activity/>Структура</button>}
        {profile?.role === "admin" && <button className={page === "users" ? "active" : ""} onClick={() => setPage("users")}><Users/>Пользователи</button>}
        {profile?.role === "admin" && <button className={page === "boards" ? "active" : ""} onClick={() => setPage("boards")}><Layers/>Доски</button>}
        {profile?.role === "student" && <button className={page === "chats" ? "active" : ""} onClick={() => setPage("chats")}><MessageCircle/>Диалоги</button>}
      </nav>
      <div className="sidebar-bottom">
        {profile?.role === "admin" && <button type="button" className={`logout desktop-admin-extra${page === "additional" ? " active" : ""}`} onClick={() => setPage("additional")}><Info size={18}/>Дополнительно</button>}
        <button type="button" className="logout desktop-sidebar-logout" onClick={signOut}><LogOut size={18}/>Выход</button>
        <div className="mobile-quick-actions">
          {pushToggle}
          <button type="button" className="theme-toggle" onClick={toggleTheme} title={theme === "dark-soft" ? "Светлая тема" : "Тёмная soft-тема"} aria-label={theme === "dark-soft" ? "Включить светлую тему" : "Включить тёмную soft-тему"}>
            {theme === "dark-soft" ? <Sun size={17}/> : <Moon size={17}/>}
          </button>
          <button className="logout" onClick={signOut} title="Выйти" aria-label="Выйти"><LogOut/></button>
        </div>
      </div>
    </aside>

    <main className="main chats-main">
      <header className="topbar">
        <small className="topbar-user">{profile?.full_name}</small>
        <div className="topbar-actions">
          {pushToggle}
          <button type="button" className="theme-toggle" onClick={toggleTheme} title={theme === "dark-soft" ? "Светлая тема" : "Тёмная soft-тема"} aria-label={theme === "dark-soft" ? "Включить светлую тему" : "Включить тёмную soft-тему"}>
            {theme === "dark-soft" ? <Sun size={17}/> : <Moon size={17}/>}
          </button>
        </div>
      </header>
      <div className={"content" + (page === "chats" ? " chats-content" : "")}>
        {error && <div className="alert alert-row">{error}<button onClick={() => setError("")}><X/></button></div>}
        {page === "graph" && <StructurePage profile={profile} teacherGraph={teacherGraph} overview={overview} openCreate={openCreate} allTeachers={allTeachers} studentsByTeacherId={studentsByTeacherId} openEdit={openEdit} setTeacherId={setTeacherId} setStudentId={setStudentId} allStudents={allStudents} setModal={setModal} unassignedStudents={unassignedStudents} />}
        {page === "boards" && profile?.role === "admin" && <BoardsPage boardObjects={boardObjects} saveBoardObjectPosition={saveBoardObjectPosition} createBoardObject={createBoardObject} deleteBoardObject={deleteBoardObject} />}
        {page === "users" && <UsersPage visibleUsers={visibleUsers} search={search} setSearch={setSearch} userSort={userSort} setUserSort={setUserSort} openCreate={openCreate} disconnectTelegram={disconnectTelegram} makeCode={makeCode} userInfo={userInfo} setUserInfo={setUserInfo} openEdit={openEdit} removeUser={removeUser} />}
        {page === "chats" && <ChatsPage profile={profile} chatSection={chatSection} setChatSection={setChatSection} personalChats={personalChats} setSelectedChat={setSelectedChat} setMessages={setMessages} chatFilter={chatFilter} setChatFilter={setChatFilter} openCreatePersonalChat={openCreatePersonalChat} chatSearch={chatSearch} setChatSearch={setChatSearch} visibleChats={visibleChats} openChat={openChat} selectedChat={selectedChat} setPage={setPage} draft={draft} setDraft={setDraft} messageFilter={messageFilter} setMessageFilter={setMessageFilter} messagesViewportRef={messagesViewportRef} visibleMessages={visibleMessages} messages={messages} setDeleteMessageCandidate={setDeleteMessageCandidate} attachment={attachment} setAttachment={setAttachment} sendChatMessage={sendChatMessage} />}

        {page === "additional" && profile?.role === "admin" && <AdditionalPage dataStats={dataStats} dataBusy={dataBusy} loadDataStats={loadDataStats} downloadAdminFile={downloadAdminFile} uploadAdminFile={uploadAdminFile} retentionDays={retentionDays} setRetentionDays={setRetentionDays} cleanupOldDialogues={cleanupOldDialogues} />}
      </div>
    </main>

    {modal && modal.mode !== "create-personal" && <div className="overlay" onMouseDown={() => setModal(null)}><section className={`modal${modal.mode === "create" ? " create-participant-modal" : modal.mode === "edit" ? " participant-profile-modal" : ""}`} onMouseDown={e => e.stopPropagation()}>
      <div className="modal-head"><div><div className="eyebrow">{modal.mode === "create" ? "НОВЫЙ УЧАСТНИК" : modal.mode === "edit" ? "ПРОФИЛЬ УЧАСТНИКА" : "СВЯЗЬ УЧЕНИКА И УЧИТЕЛЯ"}</div><h2>{modal.mode === "create" ? "Добавить участника" : modal.mode === "edit" ? "Редактировать" : "Назначить ученика"}</h2></div><button className="icon-btn" onClick={() => setModal(null)}><X/></button></div>
      {modal.mode === "assign" ? <form className="stack" onSubmit={assign}>
        <label>Учитель<select value={teacherId} onChange={e => setTeacherId(e.target.value)} required>{allTeachers.map(t => <option value={t.id} key={t.id}>{t.full_name}</option>)}</select></label>
        <label>Ученик<select value={studentId} onChange={e => setStudentId(e.target.value)} required>{allStudents.map(s => <option value={s.id} key={s.id}>{s.full_name}</option>)}</select></label>
        <p className="hint">Если у ученика уже есть активное назначение, оно будет заменено новым.</p>
        <button className="btn primary" disabled={!allStudents.length}>Создать связь</button>
      </form> : <form className="stack" onSubmit={saveUser}>
        <label>Имя и фамилия<input value={name} onChange={e => { const nextName = e.target.value; setName(nextName); if (!panelLogin || panelLogin === name) setPanelLogin(nextName); }} minLength="2" maxLength="160" required autoFocus/></label>
        {role === "student" && <label>Доп. инфо<input value={additionalInfo} onChange={e => setAdditionalInfo(e.target.value)} maxLength="500"/></label>}
        <label>Роль<select value={role} onChange={e => setRole(e.target.value)}><option value="teacher">Учитель</option><option value="student">Ученик</option></select></label>
        <label>Telegram ID <input type="text" inputMode="numeric" pattern="[0-9]*" value={telegramId} onChange={e => setTelegramId(e.target.value)} /></label>
        {["teacher", "student"].includes(role) && <>
          <div className="panel-credentials-panel">
            <div className="panel-credential-row panel-login-edit-row">
              <label htmlFor="panel-web-login">Логин веб-панели</label>
              <input id="panel-web-login" value={panelLogin || name} onChange={e => setPanelLogin(e.target.value)} minLength="2" maxLength="160" required autoComplete="off" />
            </div>
            {modal.mode === "edit" && users.find(u => u.id === modal.id)?.role === role && <div className="panel-credential-row panel-access-row">
              <span>Код доступа</span>
              <div className="panel-access-value"><b>XXXX-XXXX</b><button type="button" className="btn outline password-code-refresh" onClick={regeneratePanelAccessCode} disabled={savingUser} title="Старый код сразу перестанет действовать"><RefreshCw size={12}/>Обновить код</button></div>
            </div>}
          </div>
        </>}
        {modal.mode === "edit" && role !== users.find(u => u.id === modal.id)?.role && <p className="hint">При смене роли активные назначения будут закрыты. История переписок сохранится.</p>}
        <div className="modal-actions"><button className="btn primary" disabled={savingUser}>{savingUser ? "Сохраняем…" : <><Check/>Сохранить</>}</button>{modal.mode === "edit" && <button type="button" className="user-action-btn danger-icon user-delete" onClick={() => removeUser(users.find(u => u.id === modal.id))} disabled={savingUser} title="Удалить пользователя" aria-label="Удалить пользователя"><Trash2 size={16}/></button>}</div>
      </form>}
    </section></div>}

    {modal?.mode === "create-personal" && <div className="overlay" onMouseDown={() => setModal(null)}><section className="modal create-participant-modal" role="dialog" aria-modal="true" aria-labelledby="personal-chat-title" onMouseDown={e => e.stopPropagation()}>
      <div className="modal-head"><div><div className="eyebrow">ЛИЧНЫЕ СООБЩЕНИЯ</div><h2 id="personal-chat-title">Создать диалог</h2></div><button type="button" className="icon-btn" onClick={() => setModal(null)} aria-label="Закрыть"><X/></button></div>
      <form className="stack" onSubmit={event => {
        event.preventDefault();
        const value = event.currentTarget.elements.participant.value.trim().toLocaleLowerCase("ru");
        const selected = users.find(user => ["teacher", "student"].includes(user.role) && user.full_name.trim().toLocaleLowerCase("ru") === value);
        if (selected) void createPersonalChat(selected.id);
        else setError("Выберите участника из списка учителей и учеников");
      }}>
        <label>Участник<input name="participant" list="personal-participant-options" placeholder="Начните вводить имя" autoComplete="off" autoFocus required/></label>
        <datalist id="personal-participant-options">{users.filter(user => ["teacher", "student"].includes(user.role)).map(user => <option value={user.full_name} key={user.id}>{user.role === "teacher" ? "Учитель" : "Ученик"}</option>)}</datalist>
        <p className="hint">Начните вводить имя и выберите нужного участника. Личный диалог будет доступен только внутри UknowApp.</p>
        {error && <p className="form-error" role="alert">{error}</p>}
        <div className="modal-actions"><button type="button" className="btn ghost" onClick={() => setModal(null)}>Отмена</button><button type="submit" className="btn primary">Создать диалог</button></div>
      </form>
    </section></div>}
    {deleteCandidate && <div className="overlay" onMouseDown={() => !deletingUser && setDeleteCandidate(null)}>
      <section className="modal confirm-delete-modal" role="alertdialog" aria-modal="true" aria-labelledby="delete-user-title" onMouseDown={e => e.stopPropagation()}>
        <div className="modal-head">
          <div><div className="eyebrow">УДАЛЕНИЕ УЧАСТНИКА</div><h2 id="delete-user-title">Удалить участника?</h2></div>
          <button className="icon-btn" type="button" onClick={() => setDeleteCandidate(null)} disabled={deletingUser} aria-label="Закрыть"><X/></button>
        </div>
        <p className="hint">Профиль «<b>{deleteCandidate.full_name}</b>», связанные переписки и сообщения будут удалены. Это действие нельзя отменить.</p>
        <div className="modal-actions">
          <button type="button" className="btn ghost" onClick={() => setDeleteCandidate(null)} disabled={deletingUser}>Отмена</button>
          <button type="button" className="btn danger" onClick={confirmRemoveUser} disabled={deletingUser}>{deletingUser ? "Удаляем…" : <><Trash2/>Удалить участника</>}</button>
        </div>
      </section>
    </div>}
    {deleteMessageCandidate && <div className="overlay" onMouseDown={() => !deletingMessage && setDeleteMessageCandidate(null)}>
      <section className="modal confirm-delete-modal" role="alertdialog" aria-modal="true" aria-labelledby="delete-message-title" onMouseDown={e => e.stopPropagation()}>
        <div className="modal-head">
          <div><div className="eyebrow">УДАЛЕНИЕ СООБЩЕНИЯ</div><h2 id="delete-message-title">Удалить у всех?</h2></div>
          <button className="icon-btn" type="button" onClick={() => setDeleteMessageCandidate(null)} disabled={deletingMessage} aria-label="Закрыть"><X/></button>
        </div>
        <p className="hint">{selectedChat?.type === "personal" ? "Сообщение будет удалено из личного диалога UknowApp. Чужие сообщения удалить нельзя." : "Сообщение будет удалено из переписки UknowApp и предпринята попытка удалить его копии в Telegram у всех получателей. Чужие сообщения удалить нельзя."}</p>
        <div className="message-delete-preview">{deleteMessageCandidate.text || deleteMessageCandidate.metadata?.media?.file_name || "Вложение"}</div>
        <div className="modal-actions">
          <button type="button" className="btn ghost" onClick={() => setDeleteMessageCandidate(null)} disabled={deletingMessage}>Отмена</button>
          <button type="button" className="btn danger" onClick={confirmDeleteMessage} disabled={deletingMessage}>{deletingMessage ? "Удаляем…" : <><Trash2/>Удалить у всех</>}</button>
        </div>
      </section>
    </div>}
    {disconnectCandidate && <div className="overlay" onMouseDown={() => !disconnectingTelegram && setDisconnectCandidate(null)}>
      <section className="modal confirm-delete-modal" role="alertdialog" aria-modal="true" aria-labelledby="disconnect-telegram-title" onMouseDown={e => e.stopPropagation()}>
        <div className="modal-head">
          <div><div className="eyebrow">ОТКЛЮЧЕНИЕ TELEGRAM</div><h2 id="disconnect-telegram-title">Отключить Telegram?</h2></div>
          <button className="icon-btn" type="button" onClick={() => setDisconnectCandidate(null)} disabled={disconnectingTelegram} aria-label="Закрыть"><X/></button>
        </div>
        <p className="hint">Отключить Telegram у пользователя «<b>{disconnectCandidate.full_name}</b>»? Профиль и история переписки останутся в системе. Отправлять и получать сообщения через бота он не сможет до повторного подключения.</p>
        <div className="modal-actions">
          <button type="button" className="btn ghost" onClick={() => setDisconnectCandidate(null)} disabled={disconnectingTelegram}>Отмена</button>
          <button type="button" className="btn danger" onClick={confirmDisconnectTelegram} disabled={disconnectingTelegram}>{disconnectingTelegram ? "Отключаем…" : "Отключить Telegram"}</button>
        </div>
      </section>
    </div>}
    {issuedCredential && <div className="overlay" onMouseDown={() => setIssuedCredential(null)}><section className="modal credential-modal" onMouseDown={e => e.stopPropagation()}>
      <div className="modal-head"><div><div className="eyebrow">{issuedCredential.role === "student" ? "ЕДИНЫЙ КОД ДОСТУПА УЧЕНИКА" : "ЕДИНЫЙ КОД ДОСТУПА УЧИТЕЛЯ"}</div><h2>{issuedCredential.full_name}</h2></div><button className="icon-btn" onClick={() => setIssuedCredential(null)}><X/></button></div>
      <div className="credential-field">
        <div className="credential-field-label">Логин</div>
        <div className="credential-field-value"><b>{issuedCredential.username}</b><button type="button" className="icon-btn" onClick={async () => notify(await copyText(issuedCredential.username) ? "Логин скопирован" : "Не удалось скопировать логин")} aria-label="Скопировать логин"><Copy size={16}/></button></div>
      </div>
      <div className="credential-field credential-field-code">
        <div className="credential-field-label">Код доступа</div>
        <div className="credential-field-value"><b>{issuedCredential.code}</b><button type="button" className="icon-btn" onClick={async () => notify(await copyText(issuedCredential.code) ? "Код доступа скопирован" : "Не удалось скопировать код доступа")} aria-label="Скопировать код доступа"><Copy size={16}/></button></div>
      </div>
      <div className="modal-actions credential-actions"><button type="button" className="btn primary" onClick={async () => notify(await copyText("Логин: " + issuedCredential.username + "\nКод доступа: " + issuedCredential.code) ? "Данные для входа скопированы" : "Не удалось скопировать данные")}><Copy size={16}/>Скопировать данные</button></div>
    </section></div>}
    {code && <div className="overlay" onMouseDown={() => setCode(null)}><section className="modal" onMouseDown={e => e.stopPropagation()}><div className="modal-head"><div><div className="eyebrow">ПОДКЛЮЧЕНИЕ TELEGRAM</div><h2>{code.full_name}</h2></div><button className="icon-btn" onClick={() => setCode(null)}><X/></button></div><div className="invite-code">{code.code}</div><p className="hint">{code.shared_access ? `Это единый код ${code.role === "student" ? "ученика" : "учителя"}: он подходит для входа в веб-панель вместе с логином и для подключения Telegram. Он действует, пока администратор не заменит его новым.` : "Передайте этот код ученику для подключения Telegram. Он действует до первого успешного подключения и используется один раз."}</p><div className="modal-actions"><button className="btn ghost" onClick={() => setCode(null)}>Закрыть</button><button className="btn primary" onClick={async () => notify(await copyText(code.code) ? "Код скопирован" : "Не удалось скопировать код")}><Copy/>Скопировать</button></div></section></div>}
    {toast && <div className="toast"><Check/>{toast}</div>}
  </div>;
}