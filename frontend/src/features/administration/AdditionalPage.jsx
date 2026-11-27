import { createUniqueId } from "solid-js";
import {
  IconArchive as ArchiveIcon,
  IconChevronDown as ChevronDown,
  IconClock3 as Clock3,
  IconDatabase as DatabaseIcon,
  IconDownload as Download,
  IconUpload as Upload,
  IconRefreshCw as RefreshCw,
  IconTrash2 as Trash2,
  IconInfo as Info,
  IconX as X,
} from "../../shared/components/Icons.jsx";
import Panel from "../../shared/components/Panel.jsx";
import ConfirmDialog from "../../shared/components/ConfirmDialog.jsx";
import Button from "../../shared/components/Button.jsx";
import IconButton from "../../shared/components/IconButton.jsx";
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
function DataInfo(options) {
  const id = createUniqueId();
  return (
    <>
      <IconButton
        class="data-info-btn"
        size="compact"
        popovertarget={id}
        aria-controls={id}
        aria-haspopup="dialog"
        title={options.title}
        aria-label={options.title}
      >
        <Info size={16} aria-hidden="true" />
      </IconButton>
      <section id={id} popover="auto" class="message-delivery-popover data-info-popover" role="dialog" aria-label={options.title}>
        <div class="message-delivery-popover-heading">
          <h3>{options.title}</h3>
          <button type="button" class="message-delivery-popover-close" popovertarget={id} popovertargetaction="hide" aria-label="Закрыть подсказку">
            <X size={16} aria-hidden="true" />
          </button>
        </div>
        <ul>{options.children}</ul>
      </section>
    </>
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
          <div class="data-refresh">
            <p class="data-stats-loading" role="status">
              <span class={options.statsLoading ? "is-loading" : ""}>Обновляем данные…</span>
            </p>
            <Button
              variant="outline"
              class="data-action-btn"
              onClick={options.loadDataStats}
              disabled={options.dataBusy || options.statsLoading}
              aria-busy={options.statsLoading}
            >
              <RefreshCw size={16} aria-hidden="true" />
              Обновить
            </Button>
          </div>
        </div>
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
          <details class="data-stat-card">
            <summary class="data-stat-heading">
              <span class="data-tool-icon" aria-hidden="true"><DatabaseIcon /></span>
              <span>База данных <small>{isPostgres() ? "PostgreSQL" : "SQLite"}</small></span>
              <span class="data-stat-metric">
                <b class="data-stat-value">{options.dataStats?.database_bytes != null ? formatBytes(options.dataStats.database_bytes) : "—"}</b>
                <small>{options.dataStats?.users ?? "—"} пользователей</small>
              </span>
              <ChevronDown size={16} aria-hidden="true" />
            </summary>
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
          <details class="data-stat-card">
            <summary class="data-stat-heading">
              <span class="data-tool-icon" aria-hidden="true"><ArchiveIcon /></span>
              <span>Вложения из переписок</span>
              <span class="data-stat-metric">
                <b class="data-stat-value">{options.dataStats ? formatBytes(options.dataStats.media_bytes) : "—"}</b>
                <small>{options.dataStats?.media_files ?? "—"} файлов</small>
              </span>
              <ChevronDown size={16} aria-hidden="true" />
            </summary>
            <div class="data-stat-details">
              <span>Изображения <b>{options.dataStats?.media_images ?? "—"}</b></span>
              <span>Аудио <b>{options.dataStats?.media_audio ?? "—"}</b></span>
              <span>Видео <b>{options.dataStats?.media_videos ?? "—"}</b></span>
              <span>Другие файлы <b>{options.dataStats?.media_other ?? "—"}</b></span>
            </div>
          </details>
        </div>
        <section class="data-tools-grid" aria-labelledby="data-backups-title">
          <div class="data-tools-heading">
            <h3 id="data-backups-title">Резервные копии и очистка</h3>
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
                PostgreSQL: сохраните базу через pg_dump, вложения — отдельно.
              </p>
            )}
          </div>
          <article class="data-tool-card">
            <span class="data-tool-icon" aria-hidden="true"><ArchiveIcon /></span>
            <div class="data-tool-copy">
              <h4>Полная копия <small>ZIP</small></h4>
              <p>База, вложения и файлы приложения</p>
            </div>
            <DataInfo title="О полной копии">
              <li><strong>Состав ZIP</strong><span>Пользователи, назначения, переписки, доступные вложения, ключ Web Push и остальные файлы каталога data. Отсутствующие вложения не попадут в архив.</span></li>
              <li><strong>Восстановление</strong><span>Текущая база и файлы будут заменены. В Docker backend перезапустится автоматически, при локальном запуске — вручную. Может потребоваться повторный вход.</span></li>
              <li><strong>Настройки</strong><span>Файл .env и настройки Telegram и MAX сохраняйте отдельно.</span></li>
              {isPostgres() && <li><strong>PostgreSQL</strong><span>Сохраните базу через pg_dump, вложения скачайте отдельно.</span></li>}
            </DataInfo>
            <div class="data-tool-actions">
              <Button
                variant="outline"
                class="data-action-btn"
                aria-label="Скачать полную копию"
                onClick={() => options.downloadAdminFile("full")}
                disabled={options.dataBusy || !sqliteBackupsAvailable()}
              >
                <Download size={16} aria-hidden="true" /> Скачать
              </Button>
              <label class="btn outline data-action-btn data-upload-label">
                <Upload size={16} aria-hidden="true" />
                {options.dataBusy ? "Обработка…" : "Восстановить"}
                <input
                  type="file"
                  aria-label="Восстановить из ZIP"
                  accept=".zip,application/zip"
                  disabled={options.dataBusy || !sqliteBackupsAvailable()}
                  onInput={(e) => {
                    options.uploadAdminFile("full", e.target.files?.[0]);
                    e.target.value = "";
                  }}
                />
              </label>
            </div>
          </article>
          <article class="data-tool-card">
            <span class="data-tool-icon" aria-hidden="true"><DatabaseIcon /></span>
            <div class="data-tool-copy">
              <h4>База данных <small>SQLite</small></h4>
              <p>Данные и переписки без вложений</p>
            </div>
            <DataInfo title="О копии базы данных">
              <li><strong>Состав SQLite</strong><span>Пользователи, назначения и переписки без файлов вложений.</span></li>
              <li><strong>Восстановление</strong><span>Поддерживаются .db, .sqlite и .sqlite3. Текущая база будет заменена; файлы вложений должны быть доступны на сервере. Backend перезапустится в Docker автоматически, при локальном запуске — вручную. При ошибке исходная база будет восстановлена.</span></li>
              {isPostgres() && <li><strong>PostgreSQL</strong><span>Используйте pg_dump вместо SQLite.</span></li>}
            </DataInfo>
            <div class="data-tool-actions">
              <Button
                variant="outline"
                class="data-action-btn"
                aria-label="Скачать базу"
                onClick={() => options.downloadAdminFile("database")}
                disabled={options.dataBusy || !sqliteBackupsAvailable()}
              >
                <Download size={16} aria-hidden="true" /> Скачать
              </Button>
              <label class="btn outline data-action-btn data-upload-label">
                <Upload size={16} aria-hidden="true" />
                {options.dataBusy ? "Обработка…" : "Восстановить"}
                <input
                  type="file"
                  aria-label="Восстановить SQLite"
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
            <DataInfo title="Об архиве вложений">
              <li><strong>Состав ZIP</strong><span>Фото, голосовые сообщения, аудио, видео и документы без базы и текстов переписки.</span></li>
              <li><strong>Только скачивание</strong><span>Отдельное восстановление этого ZIP через панель не поддерживается.</span></li>
            </DataInfo>
            <div class="data-tool-actions">
              <Button
                variant="outline"
                class="data-action-btn"
                aria-label="Скачать вложения"
                onClick={() => options.downloadAdminFile("media")}
                disabled={options.dataBusy}
              >
                <Download size={16} aria-hidden="true" /> Скачать
              </Button>
            </div>
          </article>
          <article class="data-tool-card data-cleanup-card">
            <span class="data-tool-icon" aria-hidden="true"><Trash2 /></span>
            <div class="data-tool-copy">
              <h4>Очистка сообщений</h4>
              <p><label for="data-retention-days">Удалить старше</label> выбранного срока</p>
            </div>
            <DataInfo title="Об очистке сообщений">
              <li><strong>Что удаляется</strong><span>Сообщения и вложения старше выбранного срока в учебных и личных переписках.</span></li>
              <li><strong>Что остаётся</strong><span>Пользователи, назначения и диалоги сохраняются.</span></li>
              <li><strong>Важно</strong><span>Отменить удаление нельзя. Перед очисткой можно скачать резервную копию.</span></li>
            </DataInfo>
            <div class="data-tool-actions data-cleanup-actions">
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
              <Button
                variant="outline"
                aria-label="Очистить данные"
                class="data-action-btn data-action-danger"
                onClick={options.cleanupOldDialogues}
                disabled={options.dataBusy}
              >
                <Trash2 size={16} aria-hidden="true" /> Очистить
              </Button>
            </div>
          </article>
        </section>
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
