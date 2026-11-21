import { useCallback, useEffect, useState } from "react";
import {
  cleanupAdminDialogues, downloadAdminBackup, getAdminDataStats, getRestoreStatus, uploadAdminBackup,
} from "../../../features/administration/services/adminDataApi.js";

export function useAdminDataController({
  auth, profile, page, request, refresh, notify, setError,
  setSelectedChat, setMessages,
}) {
  const [dataStats, setDataStats] = useState(null);
  const [dataBusy, setDataBusy] = useState(false);
  const [restore, setRestore] = useState(null);
  const pendingId = restore?.status === "pending" ? restore.id : null;
  const [retentionDays, setRetentionDays] = useState("30");

  const loadDataStats = useCallback(async () => {
    try {
      const stats = await getAdminDataStats(request);
      setDataStats(stats);
      setRestore(current => current?.status === "pending" ? current : stats.restore);
    } catch (error) {
      setError(error.message);
    }
  }, [request, setError]);

  useEffect(() => {
    if (auth && profile?.role === "admin" && page === "additional") void loadDataStats();
  }, [auth, profile?.role, page, loadDataStats]);

  useEffect(() => {
    if (!pendingId) return;
    const controller = new AbortController();
    let timer;
    let delay = 1000;
    const check = async () => {
      try {
        const result = await getRestoreStatus(controller.signal);
        if (controller.signal.aborted) return;
        if (result?.status === "login") {
          window.location.reload();
          return;
        }
        if (result?.id === pendingId && result.status !== "pending") {
          setRestore(result);
          await loadDataStats();
          return;
        }
      } catch {
        // The backend can be unavailable while Docker restarts it.
      }
      if (!controller.signal.aborted) {
        delay = Math.min(delay * 2, 10000);
        timer = window.setTimeout(check, delay);
      }
    };
    timer = window.setTimeout(check, delay);
    return () => { controller.abort(); window.clearTimeout(timer); };
  }, [pendingId, loadDataStats]);

  const downloadAdminFile = useCallback(async kind => {
    try {
      const blob = await downloadAdminBackup(kind);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = ({
        full: "uknowapp-full-backup.zip",
        database: "uknowapp-backup.sqlite3",
        media: "uknowapp-media.zip",
      })[kind] || "uknowapp-backup";
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      notify("Файл подготовлен к скачиванию");
    } catch (error) {
      setError(error.message);
    }
  }, [notify, setError]);

  const uploadAdminFile = useCallback(async (kind, file) => {
    if (!file) return;
    const warning = kind === "full"
      ? "Подготовить перенос UknowApp из этой копии? После перезапуска backend весь текущий каталог data будет заменён содержимым архива."
      : "Заменить текущую базу данных загруженной копией? Все текущие данные будут перезаписаны.";
    if (!window.confirm(warning)) return;
    setDataBusy(true);
    setError("");
    try {
      const result = await uploadAdminBackup(kind, file);
      if (kind === "full" && result.restart_required) {
        setRestore({ id: result.restore_id, status: "pending" });
        const notice = [result.message, ...(result.warnings || [])].filter(Boolean).join(" ");
        notify(notice);
        return;
      }
      notify("База данных восстановлена. Перезагрузите панель.");
      await loadDataStats();
      if (kind === "database") {
        setSelectedChat(null);
        setMessages([]);
        await refresh();
      }
    } catch (error) {
      setError(error.message);
    } finally {
      setDataBusy(false);
    }
  }, [setError, notify, loadDataStats, setSelectedChat, setMessages, refresh]);

  const cleanupOldDialogues = useCallback(async () => {
    const days = Number(retentionDays);
    if (!window.confirm("Удалить переписки и медиафайлы старше " + days + " дней? Действие необратимо.")) return;
    setDataBusy(true);
    setError("");
    try {
      const result = await cleanupAdminDialogues(request, days);
      notify("Удалено сообщений: " + result.deleted_messages + ", личных: " + result.deleted_personal_messages + ", медиафайлов: " + result.deleted_media_files);
      await loadDataStats();
      await refresh();
    } catch (error) {
      setError(error.message);
    } finally {
      setDataBusy(false);
    }
  }, [retentionDays, setError, request, notify, loadDataStats, refresh]);

  return {
    dataStats, restore, dataBusy: dataBusy || Boolean(pendingId), retentionDays, setRetentionDays,
    loadDataStats, downloadAdminFile, uploadAdminFile, cleanupOldDialogues,
  };
}
