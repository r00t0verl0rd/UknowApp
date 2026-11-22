import GraduationCap from "lucide-react/dist/esm/icons/graduation-cap.js";
import Info from "lucide-react/dist/esm/icons/info.js";
import Link2 from "lucide-react/dist/esm/icons/link-2.js";
import Pencil from "lucide-react/dist/esm/icons/pencil.js";
import Plus from "lucide-react/dist/esm/icons/plus.js";
import Search from "lucide-react/dist/esm/icons/search.js";
import Smile from "lucide-react/dist/esm/icons/smile.js";
import Trash2 from "lucide-react/dist/esm/icons/trash-2.js";
import Unlink from "lucide-react/dist/esm/icons/unlink.js";
import Users from "lucide-react/dist/esm/icons/users.js";
import X from "lucide-react/dist/esm/icons/x.js";
import Modal from "../../shared/components/Modal.jsx";
import Button from "../../shared/components/Button.jsx";
import IconButton from "../../shared/components/IconButton.jsx";

export default function UsersPage({ visibleUsers, search, setSearch, userSort, setUserSort, openCreate, disconnectTelegram, makeCode, userInfo, setUserInfo, openEdit, removeUser }) {
  return (
    <>
      <div className="toolbar user-toolbar">
                <div className="search workspace-search"><Search/><input aria-label="Поиск по имени" placeholder="Поиск по имени" value={search} onChange={e => setSearch(e.target.value)}/></div>
                <select className="user-sort" aria-label="Сортировка пользователей" value={userSort} onChange={e => setUserSort(e.target.value)}>
                  <option value="name-asc">По имени</option><option value="name-desc">Имя: Я — А</option><option value="teachers">Сначала учителя</option><option value="students">Сначала ученики</option>
                </select>
                <span>Всего <b className="chat-tab-count">{visibleUsers.length}</b></span>
                <Button variant="primary" className="user-add-btn" onClick={() => openCreate()}><Plus/>Добавить</Button>
              </div>
              <div className="user-list" role="region" aria-label="Список пользователей">{visibleUsers.map(user => <div className="user-row" key={user.id}>
                <div className={"avatar " + user.role}>{user.role === "teacher" ? <GraduationCap/> : user.role === "student" ? <Smile/> : <Users/>}</div>
                <b className="user-person-info">{user.full_name}</b>
                <div className="user-actions">
                  {user.telegram_id
                    ? <IconButton onClick={() => disconnectTelegram(user)} title="Отключить Telegram" aria-label="Отключить Telegram"><Unlink/></IconButton>
                    : <IconButton onClick={() => makeCode(user)} title="Создать код для подключения" aria-label="Подключить участника"><Link2/></IconButton>}
                  <div className="user-info-wrap">
                    <IconButton
                      className={"user-action-btn user-info-btn" + (userInfo === user.id ? " is-open" : "")}
                      type="button"
                      title="Информация об участнике"
                      aria-label={"Информация об участнике: " + user.full_name}
                      aria-expanded={userInfo === user.id}
                      aria-haspopup="dialog"
                      onClick={() => setUserInfo(current => current === user.id ? null : user.id)}
                    ><Info/></IconButton>
                    {userInfo === user.id && <Modal className="user-details" labelledBy="user-details-title" onClose={() => setUserInfo(null)}>
                      <div className="modal-head"><h2 id="user-details-title">{user.full_name}</h2><IconButton onClick={() => setUserInfo(null)} aria-label="Закрыть"><X size={14}/></IconButton></div>
                      <div className="user-info-line"><Link2 size={14}/><span>{user.telegram_id ? "Telegram подключён" : "Telegram не подключён"}</span></div>
                      <div className="user-info-login"><span>Telegram ID</span><b>{user.telegram_id || "Не подключён"}</b></div>
                      {["teacher", "student"].includes(user.role) && <div className="user-info-login"><span>Логин</span><b>{user.web_username || user.full_name}</b></div>}
                    </Modal>}
                  </div>
                  <IconButton className="user-action-btn edit-btn" onClick={() => openEdit(user)} title="Изменить профиль" aria-label={`Изменить профиль ${user.full_name}`}><Pencil/></IconButton>
                  <IconButton className="user-action-btn danger-icon user-delete" tone="danger" onClick={() => removeUser(user)} title="Удалить пользователя" aria-label={`Удалить пользователя ${user.full_name}`}><Trash2/></IconButton>
                </div>
              </div>)}</div>
            </>
  );
}
