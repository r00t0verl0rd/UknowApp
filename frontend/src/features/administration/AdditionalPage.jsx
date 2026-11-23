import {
  IconArchive as ArchiveIcon,
  IconCheck as Check,
  IconDatabase as DatabaseIcon,
  IconRefreshCw as RefreshCw,
  IconTrash2 as Trash2,
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
export default function AdditionalPage(options) {
  const isRestore = () => options.pendingConfirmation?.type === "restore";
  const confirmationText = () =>
    isRestore()
      ? options.pendingConfirmation.kind === "full"
        ? "Восстановление заменит весь каталог data содержимым архива. Сервер перезапустится, и прежняя сессия может стать недействительной. В этом случае приложение покажет результат проверки и предложит повторно войти."
        : "Восстановление заменит текущую базу данных загруженной копией. Сервер перезапустится и проверит вложения. При ошибке он вернёт прежнюю базу. Если сессия станет недействительной, приложение предложит повторно войти."
      : "Удалить переписки и медиафайлы старше " +
        (options.pendingConfirmation?.days || "") +
        " дней? Действие необратимо.";
  return (
    <>
      <Panel class="additional-panel">
        <div class="additional-heading">
          <div>
            <div class="eyebrow">ОБСЛУЖИВАНИЕ ДАННЫХ</div>
            <h2>Дополнительно</h2>
          </div>
          <button
            type="button"
            class="btn outline"
            onClick={options.loadDataStats}
            disabled={options.dataBusy || options.statsLoading}
          >
            <RefreshCw size={15} />
            Обновить
          </button>
        </div>
        {options.statsLoading && !options.dataStats && (
          <p class="data-stats-loading" role="status">Загружаем статистику сервера…</p>
        )}
        {options.statsError && (
          <div class="data-stats-feedback" role="alert">
            <div class="data-stats-feedback-copy">
              <strong>Не удалось загрузить статистику</strong>
              <p>{options.statsError.message}</p>
              <small>Резервные копии и данные пользователей не изменялись этим запросом.</small>
            </div>
            <div class="data-stats-feedback-actions">
              <Button variant="outline" onClick={options.loadDataStats} disabled={options.statsLoading}>
                Повторить загрузку
              </Button>
              {options.statsError.needsLogin && (
                <Button variant="primary" onClick={options.loginForStats}>
                  Войти повторно
                </Button>
              )}
            </div>
          </div>
        )}
        <div class="data-stats-grid">
          <article class="data-stat-card">
            <span>База данных SQLite</span>
            <b>{options.dataStats ? formatBytes(options.dataStats.database_bytes) : "—"}</b>
            <small>{options.dataStats?.users ?? "—"} пользователей</small>
            <div class="data-stat-details">
              <span>
                Учителя: <b>{options.dataStats?.teachers ?? "—"}</b>
              </span>
              <span>
                Ученики: <b>{options.dataStats?.students ?? "—"}</b>
              </span>
              <span>
                Связи учитель–ученик: <b>{options.dataStats?.assignments ?? "—"}</b>
              </span>
              <span>
                Диалоги: <b>{options.dataStats?.conversations ?? "—"}</b> ученических ·{" "}
                <b>{options.dataStats?.personal_conversations ?? "—"}</b> личных
              </span>
              <span>
                Сообщения: <b>{options.dataStats?.total_messages ?? "—"}</b> всего
              </span>
              <span class="data-stat-subline">
                Ученические: {options.dataStats?.messages ?? "—"} · Личные:{" "}
                {options.dataStats?.personal_messages ?? "—"}
              </span>
              <span>
                Telegram-группы: <b>{options.dataStats?.telegram_groups ?? "—"}</b>
              </span>
              <span>
                Действующие коды подключения: <b>{options.dataStats?.connection_codes ?? "—"}</b>
              </span>
            </div>
          </article>
          <article class="data-stat-card">
            <span>Файлы из диалогов, сохранённые на сервере</span>
            <b>{options.dataStats ? formatBytes(options.dataStats.media_bytes) : "—"}</b>
            <small>{options.dataStats?.media_files ?? "—"} файлов</small>
            <div class="data-stat-details">
              <span>
                Изображения: <b>{options.dataStats?.media_images ?? "—"}</b>
              </span>
              <span>
                Аудио: <b>{options.dataStats?.media_audio ?? "—"}</b>
              </span>
              <span>
                Видео: <b>{options.dataStats?.media_videos ?? "—"}</b>
              </span>
              <span>
                Другие файлы: <b>{options.dataStats?.media_other ?? "—"}</b>
              </span>
            </div>
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
                disabled={options.dataBusy}
              >
                Скачать полную резервную копию
              </button>
              <label class="btn outline data-upload-label">
                {options.dataBusy ? "Обработка…" : "Восстановить из полной копии"}
                <input
                  type="file"
                  accept=".zip"
                  disabled={options.dataBusy}
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
                disabled={options.dataBusy}
              >
                Скачать базу данных
              </button>
              <label class="btn outline data-upload-label">
                {options.dataBusy ? "Обработка…" : "Восстановить базу"}
                <input
                  type="file"
                  accept=".db,.sqlite,.sqlite3"
                  disabled={options.dataBusy}
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
          <b>Для резервного копирования и переноса сервера используйте полную копию.</b>
          <span>
            Архив содержит весь каталог data, включая базу, медиафайлы, ключ Web Push и другие файлы.
            Конфигурацию .env переносите отдельно.
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
          eyebrow={isRestore() ? "ВОССТАНОВЛЕНИЕ ДАННЫХ" : "ОЧИСТКА ДАННЫХ"}
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
