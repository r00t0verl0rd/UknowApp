import ArchiveIcon from "lucide-react/dist/esm/icons/archive.js";
import Check from "lucide-react/dist/esm/icons/check.js";
import DatabaseIcon from "lucide-react/dist/esm/icons/database.js";
import RefreshCw from "lucide-react/dist/esm/icons/refresh-cw.js";
import Trash2 from "lucide-react/dist/esm/icons/trash-2.js";
import Panel from "../../shared/components/Panel.jsx";

function formatBytes(bytes) {
  if (!bytes) return "0 Б";
  const units = ["Б", "КБ", "МБ", "ГБ", "ТБ"];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return (bytes / (1024 ** index)).toLocaleString("ru-RU", { maximumFractionDigits: index ? 1 : 0 }) + " " + units[index];
}

export default function AdditionalPage({ dataStats, dataBusy, loadDataStats, downloadAdminFile, uploadAdminFile, retentionDays, setRetentionDays, cleanupOldDialogues }) {
  return (
    <Panel className="additional-panel">
      <div className="additional-heading"><div><div className="eyebrow">ОБСЛУЖИВАНИЕ ДАННЫХ</div><h2>Дополнительно</h2></div><button type="button" className="btn outline" onClick={loadDataStats} disabled={dataBusy}><RefreshCw size={15}/>Обновить</button></div>
      <div className="data-stats-grid">
        <article className="data-stat-card">
          <span>База данных SQLite</span><b>{dataStats ? formatBytes(dataStats.database_bytes) : "—"}</b>
          <small>{dataStats?.users ?? "—"} пользователей</small>
          <div className="data-stat-details">
            <span>Учителя: <b>{dataStats?.teachers ?? "—"}</b></span><span>Ученики: <b>{dataStats?.students ?? "—"}</b></span>
            <span>Связи учитель–ученик: <b>{dataStats?.assignments ?? "—"}</b></span>
            <span>Диалоги: <b>{dataStats?.conversations ?? "—"}</b> ученических · <b>{dataStats?.personal_conversations ?? "—"}</b> личных</span>
            <span>Сообщения: <b>{dataStats?.total_messages ?? "—"}</b> всего</span>
            <span className="data-stat-subline">Ученические: {dataStats?.messages ?? "—"} · Личные: {dataStats?.personal_messages ?? "—"}</span>
            <span>Telegram-группы: <b>{dataStats?.telegram_groups ?? "—"}</b></span>
            <span>Действующие коды подключения: <b>{dataStats?.connection_codes ?? "—"}</b></span>
          </div>
        </article>
        <article className="data-stat-card">
          <span>Файлы из диалогов, сохранённые на сервере</span><b>{dataStats ? formatBytes(dataStats.media_bytes) : "—"}</b>
          <small>{dataStats?.media_files ?? "—"} файлов</small>
          <div className="data-stat-details">
            <span>Изображения: <b>{dataStats?.media_images ?? "—"}</b></span>
            <span>Аудио: <b>{dataStats?.media_audio ?? "—"}</b></span>
            <span>Видео: <b>{dataStats?.media_videos ?? "—"}</b></span>
            <span>Другие файлы: <b>{dataStats?.media_other ?? "—"}</b></span>
          </div>
        </article>
      </div>
      <div className="data-tools-grid">
        <article className="data-tool-card data-tool-primary">
          <div className="data-tool-icon"><ArchiveIcon/></div>
          <div className="data-tool-copy">
            <div className="data-tool-kicker">ПОЛНЫЙ ПЕРЕНОС ДАННЫХ · ZIP</div>
            <h3>Полная резервная копия UknowApp</h3>
            <p>Один архив для резервного копирования и переезда на другой сервер. В него автоматически попадает всё содержимое каталога data.</p>
            <div className="data-includes">
              <b><Check size={14}/> Что входит</b>
              <ul><li>Полная база SQLite: пользователи, роли, назначения и переписки</li><li>Все фотографии, аудио, голосовые, видео и документы</li><li>Ключ Web Push и остальные служебные файлы из data</li><li>Все будущие файлы в data автоматически, без изменения экспортера</li></ul>
            </div>
          </div>
          <div className="data-tool-actions">
            <button type="button" className="btn primary" onClick={() => downloadAdminFile("full")} disabled={dataBusy}>Скачать полную резервную копию</button>
            <label className="btn outline data-upload-label">{dataBusy ? "Обработка…" : "Восстановить из полной копии"}<input type="file" accept=".zip" disabled={dataBusy} onChange={e => { uploadAdminFile("full", e.target.files?.[0]); e.target.value = ""; }}/></label>
          </div>
          <p className="data-warning">Восстановление заменит весь каталог data. В Docker backend перезапустится автоматически; при локальном запуске перезапустите backend вручную. Файл .env, токен Telegram и конфигурация сервера в архив не входят. Перед экспортом проверяются ссылки на вложения: при отсутствующих медиафайлах полная копия не создаётся.</p>
        </article>
        <article className="data-tool-card">
          <div className="data-tool-icon"><DatabaseIcon/></div>
          <div className="data-tool-copy">
            <div className="data-tool-kicker">ТОЛЬКО БАЗА · SQLITE3</div>
            <h3>База данных отдельно</h3>
            <p>Содержит всю структуру и данные системы, включая текстовую историю сообщений и сведения о вложениях. Сами фотографии и другие файлы не входят.</p>
          </div>
          <div className="data-tool-actions">
            <button type="button" className="btn outline" onClick={() => downloadAdminFile("database")} disabled={dataBusy}>Скачать базу данных</button>
            <label className="btn outline data-upload-label">{dataBusy ? "Обработка…" : "Восстановить базу"}<input type="file" accept=".db,.sqlite,.sqlite3" disabled={dataBusy} onChange={e => { uploadAdminFile("database", e.target.files?.[0]); e.target.value = ""; }}/></label>
          </div>
          <p className="data-warning">Восстановление заменит всю текущую базу. Для полной копии используйте основной ZIP-файл.</p>
        </article>
        <article className="data-tool-card">
          <div className="data-tool-icon"><ArchiveIcon/></div>
          <div className="data-tool-copy">
            <div className="data-tool-kicker">ТОЛЬКО ФАЙЛЫ · ZIP</div>
            <h3>Медиафайлы отдельно</h3>
            <p>Архив фотографий, аудио, голосовых, видео, документов и других файлов, загруженных в переписки. Без базы данных и текстов сообщений.</p>
          </div>
          <div className="data-tool-actions">
            <button type="button" className="btn outline" onClick={() => downloadAdminFile("media")} disabled={dataBusy}>Скачать медиафайлы</button>
          </div>
        </article>
      </div>
      <div className="data-backup-hint"><b>Для резервного копирования и переноса сервера используйте полную копию.</b><span>Архив содержит весь каталог data, включая базу, медиафайлы, ключ Web Push и другие файлы. Конфигурацию .env переносите отдельно.</span></div>
      <article className="data-cleanup-card">
        <div><div className="eyebrow">ХРАНЕНИЕ И ОЧИСТКА</div><h3>Удаление старых переписок и медиа</h3><p>Удаляются сообщения старше выбранного срока и связанные с ними архивные вложения. Аккаунты, назначения и сами диалоги сохраняются.</p></div>
        <div className="data-cleanup-actions"><label>Удалять старше<select value={retentionDays} onChange={e => setRetentionDays(e.target.value)} disabled={dataBusy}><option value="30">30 дней</option><option value="60">60 дней</option><option value="180">180 дней</option><option value="360">360 дней</option></select></label><button type="button" className="btn danger" onClick={cleanupOldDialogues} disabled={dataBusy}><Trash2 size={15}/>Удалить старые данные</button></div>
      </article>
    </Panel>
  );
}
