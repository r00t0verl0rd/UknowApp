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
            <div class="data-tool-icon">
              <ArchiveIcon />
            </div>
            <div class="data-tool-copy">
              <div class="data-tool-kicker">ПОЛНЫЙ ПЕРЕНОС ДАННЫХ · ZIP</div>
              <h3>Полная резервная копия UknowApp</h3>
              <p>
                Один архив для резервного копирования и переезда на другой сервер. В него автоматически
                попадает всё содержимое каталога data.
              </p>
              <div class="data-includes">
                <b>
                  <Check size={14} /> Что входит
                </b>
                <ul>
                  <li>Полная база SQLite: пользователи, роли, назначения и переписки</li>
                  <li>Все фотографии, аудио, голосовые, видео и документы</li>
                  <li>Ключ Web Push и остальные служебные файлы из data</li>
                  <li>Все будущие файлы в data автоматически, без изменения экспортера</li>
                </ul>
              </div>
            </div>
            <div class="data-tool-actions">
              <button
                type="button"
                class="btn primary"
                onClick={() => options.downloadAdminFile("full")}
                disabled={options.dataBusy || !sqliteBackupsAvailable()}
              >
                Скачать полную резервную копию
              </button>
              <label class="btn outline data-upload-label">
                {options.dataBusy ? "Обработка…" : "Восстановить из полной копии"}
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
              <p role="status" class="data-warning">
                {options.restore.status === "completed"
                  ? "Резервная копия восстановлена."
                  : options.restore.status === "failed"
                    ? "Восстановление не выполнено. Сохранены исходные данные."
                    : "Копия принята. Ожидаем результат после перезапуска сервера."}
                {options.restore.finished_at &&
                  " " + new Date(options.restore.finished_at).toLocaleString("ru-RU")}
              </p>
            )}
            {isPostgres() && (
              <p role="status" class="data-warning">
                Резервное копирование и восстановление SQLite через ZIP недоступны для PostgreSQL.
                Для базы используйте pg_dump, а медиафайлы скачайте отдельно.
              </p>
            )}
            <p class="data-warning">
              Восстановление заменит весь каталог data. В Docker backend перезапустится автоматически; при
              локальном запуске перезапустите backend вручную. Файл .env, токен Telegram и конфигурация
              сервера в архив не входят. Перед экспортом проверяются ссылки на вложения: при отсутствующих
              медиафайлах полная копия не создаётся.
            </p>
          </article>
          <article class="data-tool-card">
            <div class="data-tool-icon">
              <DatabaseIcon />
            </div>
            <div class="data-tool-copy">
              <div class="data-tool-kicker">ТОЛЬКО БАЗА · SQLITE3</div>
              <h3>База данных отдельно</h3>
              <p>
                Содержит всю структуру и данные системы, включая текстовую историю сообщений и сведения о
                вложениях. Сами фотографии и другие файлы не входят.
              </p>
            </div>
            <div class="data-tool-actions">
              <button
                type="button"
                class="btn outline"
                onClick={() => options.downloadAdminFile("database")}
                disabled={options.dataBusy || !sqliteBackupsAvailable()}
              >
                Скачать базу данных
              </button>
              <label class="btn outline data-upload-label">
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
            <p class="data-warning">
              Восстановление заменит всю текущую базу. Для полной копии используйте основной ZIP-файл.
            </p>
          </article>
          <article class="data-tool-card">
            <div class="data-tool-icon">
              <ArchiveIcon />
            </div>
            <div class="data-tool-copy">
              <div class="data-tool-kicker">ТОЛЬКО ФАЙЛЫ · ZIP</div>
              <h3>Медиафайлы отдельно</h3>
              <p>
                Архив фотографий, аудио, голосовых, видео, документов и других файлов, загруженных в
                переписки. Без базы данных и текстов сообщений.
              </p>
            </div>
            <div class="data-tool-actions">
              <button
                type="button"
                class="btn outline"
                onClick={() => options.downloadAdminFile("media")}
                disabled={options.dataBusy}
              >
                Скачать медиафайлы
              </button>
            </div>
          </article>
        </div>
        <div class="data-backup-hint">
          <b>{isPostgres() ? "Для PostgreSQL используйте pg_dump и отдельный архив медиафайлов." : "Для резервного копирования и переноса сервера используйте полную копию."}</b>
          <span>
            {isPostgres()
              ? "Полный ZIP со встроенной базой поддерживает только SQLite. Не забудьте отдельно перенести ключ Web Push, конфигурацию и остальные файлы из data."
              : "Архив содержит весь каталог data, включая базу, медиафайлы, ключ Web Push и другие файлы. Конфигурацию .env переносите отдельно."}
          </span>
        </div>
        <article class="data-cleanup-card">
          <div>
            <div class="eyebrow">ХРАНЕНИЕ И ОЧИСТКА</div>
            <h3>Удаление старых переписок и медиа</h3>
            <p>
              Удаляются сообщения старше выбранного срока и связанные с ними архивные вложения. Аккаунты,
              назначения и сами диалоги сохраняются.
            </p>
          </div>
          <div class="data-cleanup-actions">
            <label>
              Удалять старше
              <select
                value={options.retentionDays}
                onChange={(e) => options.setRetentionDays(e.target.value)}
                disabled={options.dataBusy}
              >
                <option value="30">30 дней</option>
                <option value="60">60 дней</option>
                <option value="180">180 дней</option>
                <option value="360">360 дней</option>
              </select>
            </label>
            <button
              type="button"
              class="btn danger"
              onClick={options.cleanupOldDialogues}
              disabled={options.dataBusy}
            >
              <Trash2 size={15} />
              Удалить старые данные
            </button>
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
