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

export default function UsersPage({ visibleUsers, search, setSearch, userSort, setUserSort, openCreate, disconnectTelegram, makeCode, userInfo, setUserInfo, openEdit, removeUser }) {
  return (
    <>
      <div className="toolbar user-toolbar">
                <div className="search"><Search/><input placeholder="Поиск по имени" value={search} onChange={e => setSearch(e.target.value)}/></div>
                <select className="user-sort" aria-label="Сортировка пользователей" value={userSort} onChange={e => setUserSort(e.target.value)}>
                  <option value="name-asc">По имени</option><option value="name-desc">Имя: Я — А</option><option value="teachers">Сначала учителя</option><option value="students">Сначала ученики</option>
                </select>
                <span className="user-count">Количество пользователей: <b>{visibleUsers.length}</b></span>
                <button className="btn primary user-add-btn" onClick={() => openCreate()}><Plus/>Добавить пользователя</button>
              </div>
              <div className="user-list">{visibleUsers.map(user => <div className={"user-row" + (userInfo === user.id ? " is-info-open" : "")} key={user.id}>
                <div className={"avatar " + user.role}>{user.role === "teacher" ? <GraduationCap/> : user.role === "student" ? <Smile/> : <Users/>}</div>
                <b className="user-person-info">{user.full_name}</b>
                <div className="user-actions">
                  {user.telegram_id
                    ? <button className="user-action-btn connect-toggle disconnect" onClick={() => disconnectTelegram(user)} title="Отключить Telegram" aria-label="Отключить Telegram"><Unlink/><span>Отключить</span></button>
                    : <button className="user-action-btn connect-toggle connect" onClick={() => makeCode(user)} title="Создать код для подключения" aria-label="Подключить участника"><Link2/><span>Подключить</span></button>}
                  <div className="user-info-wrap">
                    <button
                      className={"user-action-btn user-info-btn" + (userInfo === user.id ? " is-open" : "")}
                      type="button"
                      title="Информация об участнике"
                      aria-label={"Информация об участнике: " + user.full_name}
                      aria-expanded={userInfo === user.id}
                      aria-controls={"user-info-" + user.id}
                      onClick={() => setUserInfo(current => current === user.id ? null : user.id)}
                    ><Info/></button>
                    {userInfo === user.id && <div className="user-info-popover" id={"user-info-" + user.id} role="status">
                      <div className="user-info-popover-head"><b>Информация</b><button type="button" onClick={() => setUserInfo(null)} aria-label="Закрыть"><X size={14}/></button></div>
                      <div className="user-info-line"><Link2 size={14}/><span>{user.telegram_id ? "Telegram подключён" : "Telegram не подключён"}</span></div>
                      <div className="user-info-login"><span>Telegram ID</span><b>{user.telegram_id || "Не подключён"}</b></div>
                      {["teacher", "student"].includes(user.role) && <div className="user-info-login"><span>Логин</span><b>{user.web_username || user.full_name}</b></div>}
                    </div>}
                  </div>
                  <button className="user-action-btn edit-btn" onClick={() => openEdit(user)} title="Изменить профиль" aria-label="Изменить профиль"><Pencil/></button>
                  <button className="user-action-btn danger-icon user-delete" onClick={() => removeUser(user)} title="Удалить пользователя" aria-label="Удалить пользователя"><Trash2/></button>
                </div>
              </div>)}</div>
            </>
  );
}
