import { useCallback, useEffect, useState } from "react";
import {
  cleanupAdminDialogues, downloadAdminBackup, getAdminDataStats, uploadAdminBackup,
} from "../../modules/administration/services/adminDataApi.js";

export function useAdminDataController({
  auth, profile, page, request, refresh, notify, setError,
  setSelectedChat, setMessages,
}) {
  const [dataStats, setDataStats] = useState(null);
  const [dataBusy, setDataBusy] = useState(false);
  const [retentionDays, setRetentionDays] = useState("30");

  const loadDataStats = useCallback(async () => {
    try {
      setDataStats(await getAdminDataStats(request));
    } catch (error) {
      setError(error.message);
    }
  }, [request, setError]);

  useEffect(() => {
    if (auth && profile?.role === "admin" && page === "additional") void loadDataStats();
  }, [auth, profile?.role, page, loadDataStats]);

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
      ? "Полностью восстановить UknowApp из этой копии? Текущая база данных и все медиафайлы будут заменены."
      : "Заменить текущую базу данных загруженной копией? Все текущие данные будут перезаписаны.";
    if (!window.confirm(warning)) return;
    setDataBusy(true);
    setError("");
    try {
      await uploadAdminBackup(kind, file);
      notify(kind === "full"
        ? "Полная резервная копия восстановлена. Перезагрузите панель."
        : "База данных восстановлена. Перезагрузите панель.");
      await loadDataStats();
      if (kind === "full" || kind === "database") {
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
    dataStats, dataBusy, retentionDays, setRetentionDays,
    loadDataStats, downloadAdminFile, uploadAdminFile, cleanupOldDialogues,
  };
}
