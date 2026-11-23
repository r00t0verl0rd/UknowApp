import { createSignal, createEffect } from "solid-js";
import {
  cleanupAdminDialogues,
  adminBackupUrl,
  getAdminDataStats,
  uploadAdminBackup,
} from "../../../features/administration/services/adminDataApi.js";
export function createAdminDataController(options) {
  const [dataStats, setDataStats] = createSignal(null);
  const [statsLoading, setStatsLoading] = createSignal(false);
  const [statsError, setStatsError] = createSignal(null);
  const [dataBusy, setDataBusy] = createSignal(false);
  const [restore, setRestore] = createSignal(null);
  const [retentionDays, setRetentionDays] = createSignal("30");
  const [pendingConfirmation, setPendingConfirmation] = createSignal(null);
  let statsRequestRevision = 0;
  const loadDataStats = async () => {
    const revision = ++statsRequestRevision;
    setStatsLoading(true);
    setStatsError(null);
    try {
      const stats = await getAdminDataStats();
      if (revision !== statsRequestRevision) return;
      setDataStats(stats);
      setRestore(stats.restore);
    } catch (error) {
      if (revision !== statsRequestRevision) return;
      setDataStats(null);
      setStatsError({
        message: error.message || "Не удалось получить статистику.",
        needsLogin: error.status === 401 || error.status === 403,
      });
    } finally {
      if (revision === statsRequestRevision) setStatsLoading(false);
    }
  };
  const loginForStats = () => {
    // Navigation is initiated only by the user's explicit click.
    localStorage.removeItem("uknowapp-auth");
    sessionStorage.removeItem("uknowapp-auth");
    window.location.assign("/");
  };
  createEffect(
    () => [options.auth, options.profile?.role, options.page, loadDataStats],
    () => {
      if (options.auth && options.profile?.role === "admin" && options.page === "additional")
        void loadDataStats();
    },
  );
  // The restore tracker lives above the page, survives role changes and requires
  // an explicit user action before sending them to the login screen.
  createEffect(
    () => [options.restoreFlow.phase, options.auth, options.page],
    () => {
      if (["completed", "failed"].includes(options.restoreFlow.phase) &&
          options.auth && options.page === "additional") void loadDataStats();
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
    options.restoreFlow.startUpload();
    try {
      const result = await uploadAdminBackup(kind, file);
      setRestore({ id: result.restore_id, status: "pending" });
      options.restoreFlow.beginRestore(result);
    } catch (error) {
      options.restoreFlow.uploadFailed();
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
        "Очистка завершена: удалено " +
          (result.deleted_messages + result.deleted_personal_messages) +
          " сообщений и " + result.deleted_media_files + " вложений. " +
          "Участники и назначения сохранены.",
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
    get statsError() {
      return statsError();
    },
    get statsLoading() {
      return statsLoading();
    },
    loginForStats,
    get restore() {
      const current = options.restoreFlow.current;
      if (current?.id) {
        return {
          id: current.id,
          status: ["completed", "failed"].includes(current.phase) ? current.phase : "pending",
        };
      }
      return restore();
    },
    get dataBusy() {
      return dataBusy() || options.restoreFlow.isBlocking;
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
