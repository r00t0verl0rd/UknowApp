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
import CountBadge from "../../shared/components/CountBadge.jsx";
import IconButton from "../../shared/components/IconButton.jsx";

export default function UsersPage({ visibleUsers, search, setSearch, userSort, setUserSort, openCreate, disconnectTelegram, makeCode, userInfo, setUserInfo, openEdit, removeUser }) {
  return (
    <section className="workspace-panel users-panel">
      <div className="toolbar user-toolbar">
        <div className="search workspace-search ui-toolbar-control">
          <Search/><input aria-label="Поиск по имени" placeholder="Поиск по имени" value={search} onChange={e => setSearch(e.target.value)}/>
        </div>
        <select className="user-sort ui-toolbar-control" aria-label="Сортировка пользователей" value={userSort} onChange={e => setUserSort(e.target.value)}>
          <option value="name-asc">По имени</option><option value="name-desc">Имя: Я — А</option><option value="teachers">Сначала учителя</option><option value="students">Сначала ученики</option>
        </select>
        <Button variant="primary" className="user-add-btn ui-toolbar-control" onClick={() => openCreate()}><Plus/>Добавить</Button>
        <span className="user-total ui-toolbar-control ui-toolbar-total">Всего <CountBadge as="b" value={visibleUsers.length} label="пользователей"/></span>
      </div>
              <div className="user-list" role="region" aria-label="Список пользователей">{visibleUsers.map(user => <div className="user-row" key={user.id}>
                <div className={"avatar " + user.role}>{user.role === "teacher" ? <GraduationCap/> : user.role === "student" ? <Smile/> : <Users/>}</div>
                <b className="user-person-info">{user.full_name}</b>
                <div className="user-actions">
                  <IconButton className="user-action-btn edit-btn" onClick={() => openEdit(user)} title="Изменить профиль" aria-label={`Изменить профиль ${user.full_name}`}><Pencil/></IconButton>
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
                  <IconButton className="user-action-btn danger-icon user-delete" tone="danger" onClick={() => removeUser(user)} title="Удалить пользователя" aria-label={`Удалить пользователя ${user.full_name}`}><Trash2/></IconButton>
                </div>
              </div>)}</div>
    </section>
  );
}
