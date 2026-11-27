import {
  IconArchive as ArchiveIcon,
  IconChevronDown as ChevronDown,
  IconClock3 as Clock3,
  IconDatabase as DatabaseIcon,
  IconDownload as Download,
  IconUpload as Upload,
  IconRefreshCw as RefreshCw,
  IconTrash2 as Trash2,
} from "../../shared/components/Icons.jsx";
import Panel from "../../shared/components/Panel.jsx";
import ConfirmDialog from "../../shared/components/ConfirmDialog.jsx";
import Button from "../../shared/components/Button.jsx";
function formatBytes(bytes) {
  if (!bytes) return "0 Б";
  const units = ["Б", "КБ", "МБ", "ГБ", "ТБ"];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return (
    (bytes / 1024 ** index).toLocaleString("ru-RU", {
      maximumFractionDigits: index ? 1 : 0,
    }) +
    " " +
    units[index]
  );
}
export default function AdditionalPage(options) {
  const isRestore = () => options.pendingConfirmation?.type === "restore";
  const isPostgres = () => options.dataStats?.database_engine === "postgresql";
  const sqliteBackupsAvailable = () => options.dataStats?.database_backups_supported !== false;
  const confirmationText = () =>
    isRestore()
      ? options.pendingConfirmation.kind === "full"
        ? "Архив заменит текущую базу и файлы приложения. Сервер перезапустится. Возможно, потребуется снова войти в UknowApp."
        : "Текущая база будет заменена копией. Сервер перезапустится, проверит файлы и при ошибке вернёт прежнюю базу. Возможно, потребуется войти снова."
      : "Сообщения и вложения старше " +
        (options.pendingConfirmation?.days || "") +
        " дней будут удалены. Участники и назначения останутся. Отменить удаление нельзя.";
  return (
    <>
      <Panel class="additional-panel">
        <div class="additional-heading">
          <h2>Дополнительно</h2>
          <Button
            variant="outline"
            class="data-action-btn"
            onClick={options.loadDataStats}
            disabled={options.dataBusy || options.statsLoading}
            aria-busy={options.statsLoading}
          >
            <RefreshCw size={16} aria-hidden="true" />
            {options.statsLoading ? "Обновляем…" : "Обновить"}
          </Button>
        </div>
        {options.statsLoading && (
          <p class="data-stats-loading" role="status">Собираем сведения о данных…</p>
        )}
        {options.statsError && (
          <div class="data-stats-feedback" role="alert">
            <div class="data-stats-feedback-copy">
              <strong>Не удалось загрузить статистику</strong>
              <details class="data-info-details">
                <summary>Технические подробности <ChevronDown size={15} aria-hidden="true" /></summary>
                <small>{options.statsError.message}</small>
              </details>
            </div>
            <div class="data-stats-feedback-actions">
              <Button variant="outline" class="data-action-btn" onClick={options.loadDataStats} disabled={options.statsLoading}>
                <RefreshCw size={16} aria-hidden="true" />
                Повторить загрузку
              </Button>
              {options.statsError.needsLogin && (
                <Button variant="outline" class="data-action-btn" onClick={options.loginForStats}>
                  Войти повторно
                </Button>
              )}
            </div>
          </div>
        )}
        <div class="data-stats-grid">
          <article class="data-stat-card">
            <div class="data-stat-heading">
              <span class="data-tool-icon" aria-hidden="true"><DatabaseIcon /></span>
              <span>База данных <small>{isPostgres() ? "PostgreSQL" : "SQLite"}</small></span>
            </div>
            <b class="data-stat-value">{options.dataStats?.database_bytes != null ? formatBytes(options.dataStats.database_bytes) : "—"}</b>
            <small>{options.dataStats?.users ?? "—"} пользователей</small>
            <details class="data-info-details">
              <summary>Подробнее <ChevronDown size={15} aria-hidden="true" /></summary>
              <div class="data-stat-details">
                <span>Учителя <b>{options.dataStats?.teachers ?? "—"}</b></span>
                <span>Ученики <b>{options.dataStats?.students ?? "—"}</b></span>
                <span>Назначения <b>{options.dataStats?.assignments ?? "—"}</b></span>
                <span>Учебные диалоги <b>{options.dataStats?.conversations ?? "—"}</b></span>
                <span>Личные диалоги <b>{options.dataStats?.personal_conversations ?? "—"}</b></span>
                <span>Всего сообщений <b>{options.dataStats?.total_messages ?? "—"}</b></span>
                <span>В учебных диалогах <b>{options.dataStats?.messages ?? "—"}</b></span>
                <span>В личных диалогах <b>{options.dataStats?.personal_messages ?? "—"}</b></span>
                <span>Внешние каналы <b>{options.dataStats?.external_endpoints ?? "—"}</b></span>
                <span>Коды подключения <b>{options.dataStats?.connection_codes ?? "—"}</b></span>
              </div>
            </details>
          </article>
          <article class="data-stat-card">
            <div class="data-stat-heading">
              <span class="data-tool-icon" aria-hidden="true"><ArchiveIcon /></span>
              <span>Вложения из переписок</span>
            </div>
            <b class="data-stat-value">{options.dataStats ? formatBytes(options.dataStats.media_bytes) : "—"}</b>
            <small>{options.dataStats?.media_files ?? "—"} файлов</small>
            <details class="data-info-details">
              <summary>По типам файлов <ChevronDown size={15} aria-hidden="true" /></summary>
              <div class="data-stat-details">
                <span>Изображения <b>{options.dataStats?.media_images ?? "—"}</b></span>
                <span>Аудио <b>{options.dataStats?.media_audio ?? "—"}</b></span>
                <span>Видео <b>{options.dataStats?.media_videos ?? "—"}</b></span>
                <span>Другие файлы <b>{options.dataStats?.media_other ?? "—"}</b></span>
              </div>
            </details>
          </article>
        </div>
        <section class="data-tools-grid" aria-labelledby="data-backups-title">
          <h3 id="data-backups-title">Резервные копии</h3>
          <article class="data-tool-card data-tool-primary">
            <span class="data-tool-icon" aria-hidden="true"><ArchiveIcon /></span>
            <div class="data-tool-copy">
              <h4>Полная копия <small>ZIP</small></h4>
              <p>База, вложения и файлы приложения</p>
            </div>
            <div class="data-tool-actions">
              <Button
                variant="outline"
                class="data-action-btn"
                onClick={() => options.downloadAdminFile("full")}
                disabled={options.dataBusy || !sqliteBackupsAvailable()}
              >
                <Download size={16} aria-hidden="true" /> Скачать полную копию
              </Button>
              <label class="btn outline data-action-btn data-upload-label">
                <Upload size={16} aria-hidden="true" />
                Восстановить из ZIP
                <input
                  type="file"
                  accept=".zip,application/zip"
                  disabled={options.dataBusy || !sqliteBackupsAvailable()}
                  onInput={(e) => {
                    options.uploadAdminFile("full", e.target.files?.[0]);
                    e.target.value = "";
                  }}
                />
              </label>
            </div>
            {isPostgres() && (
              <p role="status" class="data-important-note">
                PostgreSQL: используйте pg_dump для базы, вложения скачайте отдельно.
              </p>
            )}
            {options.restore && (
              <p role="status" class={"data-operation-status" + (options.restore.status === "completed" ? " is-complete" : "")}>
                {options.restore.status === "completed"
                  ? "Данные успешно восстановлены."
                  : options.restore.status === "failed"
                    ? "Восстановление не завершилось. Исходные данные сохранены."
                    : "Архив принят. Проверяем результат восстановления."}
                {options.restore.finished_at &&
                  " " + new Date(options.restore.finished_at).toLocaleString("ru-RU")}
              </p>
            )}
            <details class="data-info-details data-backup-details">
              <summary>Перед восстановлением <ChevronDown size={15} aria-hidden="true" /></summary>
              <p>Восстановление заменяет текущие данные. В Docker сервер перезапустится автоматически, при локальном запуске — вручную. Может потребоваться повторный вход.</p>
              <p>Полная копия включает данные каталога data, в том числе ключ Web Push. Все вложения должны быть доступны. Настройки .env, Telegram и MAX сохраняйте отдельно.</p>
            </details>
          </article>
          <article class="data-tool-card">
            <span class="data-tool-icon" aria-hidden="true"><DatabaseIcon /></span>
            <div class="data-tool-copy">
              <h4>База данных <small>SQLite</small></h4>
              <p>Пользователи и переписки без вложений</p>
            </div>
            <div class="data-tool-actions">
              <Button
                variant="outline"
                class="data-action-btn"
                onClick={() => options.downloadAdminFile("database")}
                disabled={options.dataBusy || !sqliteBackupsAvailable()}
              >
                <Download size={16} aria-hidden="true" /> Скачать базу
              </Button>
              <label class="btn outline data-action-btn data-upload-label">
                <Upload size={16} aria-hidden="true" />
                Восстановить SQLite
                <input
                  type="file"
                  accept=".db,.sqlite,.sqlite3"
                  disabled={options.dataBusy || !sqliteBackupsAvailable()}
                  onInput={(e) => {
                    options.uploadAdminFile("database", e.target.files?.[0]);
                    e.target.value = "";
                  }}
                />
              </label>
            </div>
          </article>
          <article class="data-tool-card">
            <span class="data-tool-icon" aria-hidden="true"><ArchiveIcon /></span>
            <div class="data-tool-copy">
              <h4>Вложения <small>ZIP</small></h4>
              <p>Фото, аудио, видео и документы</p>
            </div>
            <div class="data-tool-actions">
              <Button
                variant="outline"
                class="data-action-btn"
                onClick={() => options.downloadAdminFile("media")}
                disabled={options.dataBusy}
              >
                <Download size={16} aria-hidden="true" /> Скачать вложения
              </Button>
            </div>
          </article>
        </section>
        <article class="data-cleanup-card">
          <div class="data-cleanup-copy">
            <span class="data-tool-icon" aria-hidden="true"><Trash2 /></span>
            <div>
              <h3>Очистить старые сообщения</h3>
              <p>Сообщения и вложения. Участники и диалоги сохранятся.</p>
            </div>
          </div>
          <div class="data-cleanup-actions">
            <div class="data-retention-field">
              <label for="data-retention-days">Удалить старше</label>
              <div class="data-retention-select">
                <Clock3 size={16} aria-hidden="true" />
                <select
                  id="data-retention-days"
                  value={options.retentionDays}
                  onChange={(e) => options.setRetentionDays(e.target.value)}
                  disabled={options.dataBusy}
                >
                  <option value="30">30 дней</option>
                  <option value="60">60 дней</option>
                  <option value="180">180 дней</option>
                  <option value="360">360 дней</option>
                </select>
                <ChevronDown size={16} aria-hidden="true" />
              </div>
            </div>
            <Button
              variant="outline"
              class="data-action-btn data-action-danger"
              onClick={options.cleanupOldDialogues}
              disabled={options.dataBusy}
            >
              <Trash2 size={16} aria-hidden="true" /> Очистить данные
            </Button>
          </div>
        </article>
      </Panel>
      {options.pendingConfirmation && (
        <ConfirmDialog
          eyebrow={isRestore() ? "Резервная копия" : "Очистка переписок"}
          title={isRestore() ? "Восстановить резервную копию?" : "Удалить старые данные?"}
          titleId="admin-operation-title"
          busy={options.dataBusy}
          tone={isRestore() ? "primary" : "danger"}
          confirmLabel={isRestore() ? "Восстановить" : "Удалить данные"}
          onClose={() => options.setPendingConfirmation(null)}
          onConfirm={options.confirmPendingAction}
        >
          {confirmationText()}
        </ConfirmDialog>
      )}
    </>
  );
}
