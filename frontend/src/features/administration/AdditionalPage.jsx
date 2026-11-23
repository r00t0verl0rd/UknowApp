import {
  IconArchive as ArchiveIcon,
  IconCheck as Check,
  IconChevronDown as ChevronDown,
  IconClock3 as Clock3,
  IconDatabase as DatabaseIcon,
  IconDownload as Download,
  IconInfo as Info,
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
          <div>
            <div class="eyebrow">Данные и резервные копии</div>
            <h2>Дополнительно</h2>
            <p>Посмотрите, что хранится в UknowApp, и сохраните важные данные.</p>
          </div>
          <Button
            variant="outline"
            class="data-action-btn"
            onClick={options.loadDataStats}
            disabled={options.dataBusy || options.statsLoading}
          >
            <RefreshCw size={16} aria-hidden="true" />
            Обновить
          </Button>
        </div>
        {options.statsLoading && !options.dataStats && (
          <p class="data-stats-loading" role="status">Собираем сведения о данных…</p>
        )}
        {options.statsError && (
          <div class="data-stats-feedback" role="alert">
            <div class="data-stats-feedback-copy">
              <strong>Не удалось загрузить статистику</strong>
              <p>Данные остались без изменений. Попробуйте обновить сведения.</p>
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
                <Button variant="primary" class="data-action-btn" onClick={options.loginForStats}>
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
            <p class="data-stat-hint">В размере учтены таблицы и служебные данные.</p>
            <details class="data-info-details">
              <summary>Что хранится в базе <ChevronDown size={15} aria-hidden="true" /></summary>
              <div class="data-stat-details">
                <span>Учителя <b>{options.dataStats?.teachers ?? "—"}</b></span>
                <span>Ученики <b>{options.dataStats?.students ?? "—"}</b></span>
                <span>Назначения <b>{options.dataStats?.assignments ?? "—"}</b></span>
                <span>Учебные диалоги <b>{options.dataStats?.conversations ?? "—"}</b></span>
                <span>Личные диалоги <b>{options.dataStats?.personal_conversations ?? "—"}</b></span>
                <span>Всего сообщений <b>{options.dataStats?.total_messages ?? "—"}</b></span>
                <span>В учебных диалогах <b>{options.dataStats?.messages ?? "—"}</b></span>
                <span>В личных диалогах <b>{options.dataStats?.personal_messages ?? "—"}</b></span>
                <span>Telegram-группы <b>{options.dataStats?.telegram_groups ?? "—"}</b></span>
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
            <p class="data-stat-hint">Фото, голосовые сообщения и документы на сервере.</p>
            <details class="data-info-details">
              <summary>Посмотреть по типам <ChevronDown size={15} aria-hidden="true" /></summary>
              <div class="data-stat-details">
                <span>Изображения <b>{options.dataStats?.media_images ?? "—"}</b></span>
                <span>Аудио <b>{options.dataStats?.media_audio ?? "—"}</b></span>
                <span>Видео <b>{options.dataStats?.media_videos ?? "—"}</b></span>
                <span>Другие файлы <b>{options.dataStats?.media_other ?? "—"}</b></span>
              </div>
            </details>
          </article>
        </div>
        <div class="data-tools-grid">
          <article class="data-tool-card data-tool-primary">
            <span class="data-tool-icon" aria-hidden="true"><ArchiveIcon /></span>
            <div class="data-tool-copy">
              <div class="data-tool-kicker">Резервная копия · ZIP</div>
              <h3>Весь UknowApp в одном архиве</h3>
              <p>Сохраните данные и файлы вместе, чтобы при необходимости восстановить приложение.</p>
              <details class="data-info-details data-includes">
                <summary><Check size={15} aria-hidden="true" /> Что входит в архив <ChevronDown size={15} aria-hidden="true" /></summary>
                <ul>
                  <li>Пользователи, назначения и переписки</li>
                  <li>Фотографии, аудио, видео и документы</li>
                  <li>Ключ Web Push и другие файлы из каталога data</li>
                </ul>
              </details>
            </div>
            <div class="data-tool-actions">
              <Button
                variant="primary"
                class="data-action-btn"
                onClick={() => options.downloadAdminFile("full")}
                disabled={options.dataBusy || !sqliteBackupsAvailable()}
              >
                <Download size={16} aria-hidden="true" /> Скачать полную копию
              </Button>
              <label class="btn outline data-action-btn data-upload-label">
                <Upload size={16} aria-hidden="true" />
                {options.dataBusy ? "Обработка…" : "Восстановить из архива"}
                <input
                  type="file"
                  accept=".zip"
                  disabled={options.dataBusy || !sqliteBackupsAvailable()}
                  onInput={(e) => {
                    options.uploadAdminFile("full", e.target.files?.[0]);
                    e.target.value = "";
                  }}
                />
              </label>
            </div>
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
            {isPostgres() && (
              <p role="status" class="data-important-note">
                Для PostgreSQL сохраните базу через pg_dump, а файлы скачайте отдельно.
              </p>
            )}
            <p class="data-important-note">При восстановлении текущие данные заменятся содержимым архива.</p>
            <details class="data-info-details">
              <summary>Что важно знать перед восстановлением <ChevronDown size={15} aria-hidden="true" /></summary>
              <p class="data-note-copy">
                В Docker сервер перезапустится автоматически, при локальном запуске нужен ручной перезапуск backend.
                Настройки .env и Telegram сохраняйте отдельно. Для полной копии все вложения должны быть доступны.
              </p>
            </details>
          </article>
          <article class="data-tool-card">
            <span class="data-tool-icon" aria-hidden="true"><DatabaseIcon /></span>
            <div class="data-tool-copy">
              <div class="data-tool-kicker">Отдельная копия · SQLite</div>
              <h3>Только база данных</h3>
              <p>Пользователи, назначения и переписки без фотографий и других вложений.</p>
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
                {options.dataBusy ? "Обработка…" : "Восстановить базу"}
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
            <p class="data-important-note">Восстановление заменит текущую базу. Для переноса всех файлов используйте полную копию.</p>
          </article>
          <article class="data-tool-card">
            <span class="data-tool-icon" aria-hidden="true"><ArchiveIcon /></span>
            <div class="data-tool-copy">
              <div class="data-tool-kicker">Отдельная копия · ZIP</div>
              <h3>Только вложения</h3>
              <p>Фотографии, голосовые сообщения, видео и документы — без базы и текстов переписки.</p>
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
        </div>
        <div class="data-backup-hint">
          <Info size={18} aria-hidden="true" />
          <div>
            <b>{isPostgres() ? "Для PostgreSQL сохраните базу и файлы отдельно." : "Для переезда на другой сервер выбирайте полную копию."}</b>
            <span>{isPostgres()
              ? "Сделайте дамп через pg_dump, скачайте файлы и сохраните .env отдельно."
              : "В ней будут база и вложения. Настройки .env нужно сохранить отдельно."}</span>
          </div>
        </div>
        <article class="data-cleanup-card">
          <div class="data-cleanup-copy">
            <span class="data-tool-icon" aria-hidden="true"><Trash2 /></span>
            <div>
              <div class="data-tool-kicker">Уход за переписками</div>
              <h3>Очистить старые сообщения</h3>
              <p>Удалите старые сообщения и вложения. Пользователи, назначения и диалоги сохранятся.</p>
            </div>
          </div>
          <div class="data-cleanup-actions">
            <div class="data-retention-field">
              <label for="data-retention-days">Удалять старше</label>
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
