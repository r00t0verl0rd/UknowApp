import { createSignal, createEffect } from "solid-js";
import {
  cleanupAdminDialogues,
  adminBackupUrl,
  getAdminDataStats,
  getRestoreStatus,
  uploadAdminBackup,
} from "../../../features/administration/services/adminDataApi.js";
export function createAdminDataController(options) {
  const [dataStats, setDataStats] = createSignal(null);
  const [dataBusy, setDataBusy] = createSignal(false);
  const [restore, setRestore] = createSignal(null);
  const pendingId = () => (restore()?.status === "pending" ? restore().id : null);
  const [retentionDays, setRetentionDays] = createSignal("30");
  const [pendingConfirmation, setPendingConfirmation] = createSignal(null);
  const loadDataStats = async () => {
    try {
      const stats = await getAdminDataStats(options.request);
      setDataStats(stats);
      setRestore((current) => (current?.status === "pending" ? current : stats.restore));
    } catch (error) {
      options.setError(error.message);
    }
  };
  createEffect(
    () => [options.auth, options.profile?.role, options.page, loadDataStats],
    () => {
      if (options.auth && options.profile?.role === "admin" && options.page === "additional")
        void loadDataStats();
    },
  );
  createEffect(
    () => [pendingId(), loadDataStats],
    () => {
      if (!pendingId()) return;
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
          if (result?.id === pendingId() && result.status !== "pending") {
            setRestore(result);
            await loadDataStats();
            return;
          }
        } catch {
          // Во время перезапуска Docker backend может быть недоступен.
        }
        if (!controller.signal.aborted) {
          delay = Math.min(delay * 2, 10000);
          timer = window.setTimeout(check, delay);
        }
      };
      timer = window.setTimeout(check, delay);
      return () => {
        controller.abort();
        window.clearTimeout(timer);
      };
    },
  );
  const downloadAdminFile = async (kind) => {
    try {
      const url = adminBackupUrl(kind);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download =
        {
          full: "uknowapp-full-backup.zip",
          database: "uknowapp-backup.sqlite3",
          media: "uknowapp-media.zip",
        }[kind] || "uknowapp-backup";
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
    } catch (error) {
      options.setError(error.message);
    }
  };
  const performUploadAdminFile = async (kind, file) => {
    setDataBusy(true);
    try {
      const result = await uploadAdminBackup(kind, file);
      if (kind === "full" && result.restart_required) {
        setRestore({
          id: result.restore_id,
          status: "pending",
        });
        const notice = [result.message, ...(result.warnings || [])].filter(Boolean).join(" ");
        options.notify(notice);
        return;
      }
      options.notify("База данных восстановлена. Перезагрузите панель.");
      await loadDataStats();
      if (kind === "database") {
        options.setSelectedChat(null);
        options.setMessages([]);
        await options.refresh();
      }
    } catch (error) {
      options.setError(error.message);
    } finally {
      setDataBusy(false);
    }
  };
  const performCleanupOldDialogues = async (days) => {
    setDataBusy(true);
    try {
      const result = await cleanupAdminDialogues(options.request, days);
      options.notify(
        "Удалено сообщений: " +
          result.deleted_messages +
          ", личных: " +
          result.deleted_personal_messages +
          ", медиафайлов: " +
          result.deleted_media_files,
      );
      await loadDataStats();
      await options.refresh();
    } catch (error) {
      options.setError(error.message);
    } finally {
      setDataBusy(false);
    }
  };

  // Browser-native <dialog> показывает единое подтверждение для опасных операций.
  // File остаётся в памяти до согласия; отмена ничего не загружает.
  const uploadAdminFile = (kind, file) => {
    if (file)
      setPendingConfirmation({
        type: "restore",
        kind,
        file,
      });
  };
  const cleanupOldDialogues = () => {
    setPendingConfirmation({
      type: "cleanup",
      days: Number(retentionDays()),
    });
  };
  const confirmPendingAction = async () => {
    const current = pendingConfirmation();
    if (!current || dataBusy()) return;
    setPendingConfirmation(null);
    if (current.type === "restore") await performUploadAdminFile(current.kind, current.file);
    else await performCleanupOldDialogues(current.days);
  };
  return {
    get dataStats() {
      return dataStats();
    },
    get restore() {
      return restore();
    },
    get dataBusy() {
      return dataBusy() || Boolean(pendingId());
    },
    get retentionDays() {
      return retentionDays();
    },
    setRetentionDays,
    loadDataStats,
    downloadAdminFile,
    uploadAdminFile,
    cleanupOldDialogues,
    get pendingConfirmation() {
      return pendingConfirmation();
    },
    setPendingConfirmation,
    confirmPendingAction,
  };
}
