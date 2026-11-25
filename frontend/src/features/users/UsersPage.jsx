import { telegramId } from "./services/usersApi.js";
import { For } from "solid-js";
import {
  IconGraduationCap as GraduationCap,
  IconInfo as Info,
  IconLink2 as Link2,
  IconPencil as Pencil,
  IconPlus as Plus,
  IconSearch as Search,
  IconSmile as Smile,
  IconTrash2 as Trash2,
  IconUnlink as Unlink,
  IconUsers as Users,
  IconX as X,
} from "../../shared/components/Icons.jsx";
import Modal from "../../shared/components/Modal.jsx";
import Button from "../../shared/components/Button.jsx";
import CountBadge from "../../shared/components/CountBadge.jsx";
import IconButton from "../../shared/components/IconButton.jsx";
import ToolbarSelect from "../../shared/components/ToolbarSelect.jsx";
export default function UsersPage(options) {
  return (
    <section class="workspace-panel users-panel">
      <div class="toolbar user-toolbar">
        <div class="search workspace-search ui-toolbar-control">
          <Search />
          <input
            aria-label="Поиск по имени"
            placeholder="Поиск по имени"
            value={options.search}
            onInput={(e) => options.setSearch(e.target.value)}
          />
        </div>
        <ToolbarSelect
          class="user-sort-field"
          selectClassName="user-sort"
          aria-label="Сортировка пользователей"
          value={options.userSort}
          onChange={(e) => options.setUserSort(e.target.value)}
        >
          <option value="name-asc">По имени</option>
          <option value="name-desc">Имя: Я — А</option>
          <option value="teachers">Сначала учителя</option>
          <option value="students">Сначала ученики</option>
        </ToolbarSelect>
        <Button
          variant="primary"
          class="user-add-btn ui-toolbar-control"
          onClick={() => options.openCreate()}
        >
          <Plus />
          Добавить
        </Button>
        <span class="user-total ui-toolbar-control ui-toolbar-total">
          Всего <CountBadge as="b" value={options.visibleUsers.length} label="пользователей" />
        </span>
      </div>
      <div class="user-list" role="region" aria-label="Список пользователей">
        <For each={options.visibleUsers}>
          {(user) => (
            <div class="user-row" data-view-anchor={"user:" + user.id}>
              <div class={"avatar " + user.role}>
                {user.role === "teacher" ? (
                  <GraduationCap />
                ) : user.role === "student" ? (
                  <Smile />
                ) : (
                  <Users />
                )}
              </div>
              <b class="user-person-info">{user.full_name}</b>
              <div class="user-actions">
                <IconButton
                  class="user-action-btn edit-btn"
                  onClick={() => options.openEdit(user)}
                  title="Изменить профиль"
                  aria-label={`Изменить профиль ${user.full_name}`}
                >
                  <Pencil />
                </IconButton>
                {telegramId(user) ? (
                  <IconButton
                    onClick={() => options.disconnectTelegram(user)}
                    title="Отключить Telegram"
                    aria-label="Отключить Telegram"
                  >
                    <Unlink />
                  </IconButton>
                ) : (
                  <IconButton
                    onClick={() => options.openTelegram(user)}
                    title="Выбрать способ подключения Telegram"
                    aria-label="Подключить Telegram"
                  >
                    <Link2 />
                  </IconButton>
                )}
                <div class="user-info-wrap">
                  <IconButton
                    class={
                      "user-action-btn user-info-btn" + (options.userInfo === user.id ? " is-open" : "")
                    }
                    type="button"
                    title="Информация об участнике"
                    aria-label={"Информация об участнике: " + user.full_name}
                    aria-expanded={options.userInfo === user.id}
                    aria-haspopup="dialog"
                    onClick={() => options.setUserInfo((current) => (current === user.id ? null : user.id))}
                  >
                    <Info />
                  </IconButton>
                  {options.userInfo === user.id && (
                    <Modal
                      class="user-details"
                      labelledBy="user-details-title"
                      onClose={() => options.setUserInfo(null)}
                    >
                      <div class="modal-head">
                        <h2 id="user-details-title">{user.full_name}</h2>
                        <IconButton onClick={() => options.setUserInfo(null)} aria-label="Закрыть">
                          <X size={14} />
                        </IconButton>
                      </div>
                      <div class="user-info-line">
                        <Link2 size={14} />
                        <span>{telegramId(user) ? "Telegram подключён" : "Telegram не подключён"}</span>
                      </div>
                      <div class="user-info-login">
                        <span>Telegram ID</span>
                        <b>{telegramId(user) || "Не подключён"}</b>
                      </div>
                      {["teacher", "student"].includes(user.role) && (
                        <div class="user-info-login">
                          <span>Логин</span>
                          <b>{user.web_username || user.full_name}</b>
                        </div>
                      )}
                    </Modal>
                  )}
                </div>
                <IconButton
                  class="user-action-btn danger-icon user-delete"
                  tone="danger"
                  onClick={() => options.removeUser(user)}
                  title="Удалить пользователя"
                  aria-label={`Удалить пользователя ${user.full_name}`}
                >
                  <Trash2 />
                </IconButton>
              </div>
            </div>
          )}
        </For>
      </div>
    </section>
  );
}
