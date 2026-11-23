import { For } from "solid-js";
import { createSignal, createEffect } from "solid-js";
import {
  IconCheck as Check,
  IconCopy as Copy,
  IconRefreshCw as RefreshCw,
  IconTrash2 as Trash2,
  IconX as X,
  IconUnlink as Unlink,
} from "../../../shared/components/Icons.jsx";
import Modal from "../../../shared/components/Modal.jsx";
import ConfirmDialog from "../../../shared/components/ConfirmDialog.jsx";
import Button from "../../../shared/components/Button.jsx";
import IconButton from "../../../shared/components/IconButton.jsx";
import FormField from "../../../shared/components/FormField.jsx";
async function copyText(value) {
  try {
    if (window.isSecureContext && navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(value);
      return true;
    }
  } catch {
    // Если API буфера недоступно, используем запасной способ.
  }
  const textarea = document.createElement("textarea");
  textarea.value = value;
  textarea.setAttribute("readonly", "");
  textarea.style.position = "fixed";
  textarea.style.opacity = "0";
  textarea.style.pointerEvents = "none";
  document.body.appendChild(textarea);
  textarea.select();
  textarea.setSelectionRange(0, textarea.value.length);
  let copied = false;
  try {
    copied = document.execCommand("copy");
  } catch {
    copied = false;
  }
  textarea.remove();
  return copied;
}
export default function UserDialogs(options) {
  const [confirmNewCode, setConfirmNewCode] = createSignal(false);
  createEffect(
    () => [options.modal?.id, options.modal?.mode],
    () => {
      setConfirmNewCode(false);
    },
  );
  return (
    <>
      {options.modal && options.modal.mode !== "create-personal" && (
        <Modal
          onClose={() => options.setModal(null)}
          closeOnBackdrop={!options.savingUser}
          class={`${options.modal.mode === "create" ? "create-participant-modal" : options.modal.mode === "edit" ? "participant-profile-modal" : ""}`}
        >
          <div class="modal-head">
            <div>
              <div class="eyebrow">
                {options.modal.mode === "create"
                  ? "Новый участник"
                  : options.modal.mode === "edit"
                    ? "Профиль участника"
                    : "Назначение учителя"}
              </div>
              <h2>
                {options.modal.mode === "create"
                  ? "Добавить участника"
                  : options.modal.mode === "edit"
                    ? "Редактировать"
                    : "Назначить ученика"}
              </h2>
            </div>
            <IconButton onClick={() => options.setModal(null)}>
              <X />
            </IconButton>
          </div>
          {options.modal.mode === "assign" ? (
            <form class="stack" onSubmit={options.assign}>
              <FormField label="Учитель">
                <select
                  value={options.teacherId}
                  onChange={(event) => options.setTeacherId(event.target.value)}
                  required
                >
                  <For each={options.allTeachers}>
                    {(teacher) => <option value={teacher.id}>{teacher.full_name}</option>}
                  </For>
                </select>
              </FormField>
              <FormField label="Ученик">
                <select
                  value={options.studentId}
                  onChange={(event) => options.setStudentId(event.target.value)}
                  required
                >
                  <For each={options.allStudents}>
                    {(student) => <option value={student.id}>{student.full_name}</option>}
                  </For>
                </select>
              </FormField>
              <p class="hint">Если ученик уже занимается с другим учителем, новое назначение заменит прежнее.</p>
              <div class="modal-actions">
                <Button variant="ghost" onClick={() => options.setModal(null)}>
                  Отмена
                </Button>
                <Button type="submit" variant="primary" disabled={!options.allStudents.length}>
                  Создать связь
                </Button>
              </div>
            </form>
          ) : (
            <form class="stack" onSubmit={options.saveUser}>
              <FormField label="Имя и фамилия">
                <input
                  value={options.name}
                  onInput={(event) => {
                    const nextName = event.target.value;
                    options.setName(nextName);
                    if (!options.panelLogin || options.panelLogin === options.name)
                      options.setPanelLogin(nextName);
                  }}
                  minLength="2"
                  maxLength="160"
                  required
                  autoFocus
                />
              </FormField>
              {options.role === "student" && (
                <FormField label="Доп. инфо">
                  <input
                    value={options.additionalInfo}
                    onInput={(event) => options.setAdditionalInfo(event.target.value)}
                    maxLength="500"
                  />
                </FormField>
              )}
              <FormField label="Роль">
                <select value={options.role} onChange={(event) => options.setRole(event.target.value)}>
                  <option value="teacher">Учитель</option>
                  <option value="student">Ученик</option>
                </select>
              </FormField>
              <FormField label="Telegram ID">
                <input
                  type="text"
                  inputMode="numeric"
                  pattern="[0-9]*"
                  value={options.telegramId}
                  onInput={(event) => options.setTelegramId(event.target.value)}
                />
              </FormField>
              {["teacher", "student"].includes(options.role) && (
                <div class="panel-credentials-panel">
                  <div class="panel-credential-row panel-login-edit-row">
                    <label for="panel-web-login">Логин веб-панели</label>
                    <input
                      id="panel-web-login"
                      value={options.panelLogin || options.name}
                      onInput={(event) => options.setPanelLogin(event.target.value)}
                      minLength="2"
                      maxLength="160"
                      required
                      autoComplete="off"
                    />
                  </div>
                  {options.modal.mode !== "edit" && (
                    <p class="hint">Код входа появится после сохранения участника. Код для Telegram выдаётся отдельно.</p>
                  )}
                  {options.modal.mode === "edit" &&
                    options.users.find((user) => user.id === options.modal.id)?.role === options.role && (
                      <div class="panel-credential-row panel-access-row">
                        <span>Код входа в UknowApp</span>
                        <div class="panel-access-value">
                          <b>Скрыт</b>
                          <Button
                            variant="outline"
                            class="password-code-refresh"
                            onClick={() => setConfirmNewCode(true)}
                            disabled={options.savingUser}
                            title="Старый код сразу перестанет действовать"
                          >
                            <RefreshCw size={16} />
                            Перевыпустить
                          </Button>
                        </div>
                      </div>
                    )}
                </div>
              )}
              {options.modal.mode === "edit" &&
                options.role !== options.users.find((user) => user.id === options.modal.id)?.role && (
                  <p class="hint">
                    При смене роли активные назначения будут закрыты. История переписок сохранится.
                  </p>
                )}
              <div class="modal-actions">
                <Button variant="ghost" onClick={() => options.setModal(null)} disabled={options.savingUser}>
                  Отмена
                </Button>
                {options.modal.mode === "edit" && (
                  <IconButton
                    tone="danger"
                    class="user-action-btn danger-icon user-delete"
                    onClick={() =>
                      options.removeUser(options.users.find((user) => user.id === options.modal.id))
                    }
                    disabled={options.savingUser}
                    title="Удалить пользователя"
                    aria-label="Удалить пользователя"
                  >
                    <Trash2 size={16} />
                  </IconButton>
                )}
                <Button type="submit" variant="primary" disabled={options.savingUser}>
                  {options.savingUser ? (
                    "Сохраняем…"
                  ) : (
                    <>
                      <Check />
                      Сохранить
                    </>
                  )}
                </Button>
              </div>
            </form>
          )}
        </Modal>
      )}

      {options.modal?.mode === "edit" && confirmNewCode() && (
        <ConfirmDialog
          eyebrow="Код входа"
          title="Перевыпустить код входа?"
          titleId="new-access-code-title"
          busy={options.savingUser}
          tone="primary"
          confirmLabel="Выдать код"
          onClose={() => setConfirmNewCode(false)}
          onConfirm={async () => {
            setConfirmNewCode(false);
            await options.regeneratePanelAccessCode();
          }}
        >
          Старый код входа сразу перестанет работать, а участнику потребуется войти заново. Скопируйте новый код и передайте его участнику. Подключение Telegram сохранится.
        </ConfirmDialog>
      )}

      {options.deleteCandidate && (
        <ConfirmDialog
          eyebrow="Участник"
          title="Удалить участника?"
          titleId="delete-user-title"
          busy={options.deletingUser}
          icon={<Trash2 />}
          confirmLabel="Удалить участника"
          busyLabel="Удаляем…"
          onClose={() => options.setDeleteCandidate(null)}
          onConfirm={options.confirmRemoveUser}
        >
          Профиль «<b>{options.deleteCandidate.full_name}</b>» и связанные переписки будут удалены.
          Вернуть их после удаления не получится.
        </ConfirmDialog>
      )}

      {options.unassignCandidate && (
        <ConfirmDialog
          eyebrow="Назначение"
          title="Отвязать ученика?"
          titleId="unassign-student-title"
          busy={options.unassigningStudent}
          icon={<Unlink />}
          confirmLabel="Отвязать ученика"
          busyLabel="Отвязываем…"
          onClose={() => options.setUnassignCandidate(null)}
          onConfirm={options.confirmUnassignStudent}
        >
          Ученик «<b>{options.unassignCandidate.full_name}</b>» перейдёт в список «Без учителя».
          История переписки сохранится, но старый диалог закроется.
        </ConfirmDialog>
      )}

      {options.disconnectCandidate && (
        <ConfirmDialog
          eyebrow="Telegram"
          title="Отключить Telegram?"
          titleId="disconnect-telegram-title"
          busy={options.disconnectingTelegram}
          confirmLabel="Отключить Telegram"
          busyLabel="Отключаем…"
          onClose={() => options.setDisconnectCandidate(null)}
          onConfirm={options.confirmDisconnectTelegram}
        >
          Профиль и переписка «<b>{options.disconnectCandidate.full_name}</b>» сохранятся в UknowApp.
          Сообщения через Telegram будут доступны после повторного подключения.
        </ConfirmDialog>
      )}

      {options.issuedCredential && (
        <Modal onClose={() => options.setIssuedCredential(null)} class="credential-modal">
          <div class="modal-head">
            <div>
              <div class="eyebrow">Вход в UknowApp</div>
              <h2>{options.issuedCredential.full_name}</h2>
            </div>
            <IconButton onClick={() => options.setIssuedCredential(null)}>
              <X />
            </IconButton>
          </div>
          <div class="credential-field">
            <div class="credential-field-label">Логин</div>
            <div class="credential-field-value">
              <b>{options.issuedCredential.username}</b>
              <IconButton
                onClick={async () =>
                  options.notify(
                    (await copyText(options.issuedCredential.username))
                      ? "Логин скопирован"
                      : "Не удалось скопировать логин",
                  )
                }
                aria-label="Скопировать логин"
              >
                <Copy size={16} />
              </IconButton>
            </div>
          </div>
          <div class="credential-field credential-field-code">
            <div class="credential-field-label">Код входа</div>
            <div class="credential-field-value">
              <b>{options.issuedCredential.code}</b>
              <IconButton
                onClick={async () =>
                  options.notify(
                    (await copyText(options.issuedCredential.code))
                      ? "Код входа скопирован"
                      : "Не удалось скопировать код доступа",
                  )
                }
                aria-label="Скопировать код доступа"
              >
                <Copy size={16} />
              </IconButton>
            </div>
          </div>
          <div class="modal-actions credential-actions">
            <Button
              variant="primary"
              onClick={async () =>
                options.notify(
                  (await copyText(
                    "Логин: " +
                      options.issuedCredential.username +
                      "\nКод входа: " +
                      options.issuedCredential.code,
                  ))
                    ? "Данные для входа скопированы"
                    : "Не удалось скопировать данные",
                )
              }
            >
              <Copy size={16} />
              Скопировать данные
            </Button>
          </div>
        </Modal>
      )}

      {options.code && (
        <Modal onClose={() => options.setCode(null)}>
          <div class="modal-head">
            <div>
              <div class="eyebrow">Подключение Telegram</div>
              <h2>{options.code.full_name}</h2>
            </div>
            <IconButton onClick={() => options.setCode(null)}>
              <X />
            </IconButton>
          </div>
          <div class="invite-code">{options.code.code}</div>
          <p class="hint">
            Передайте этот код участнику, чтобы он отправил его боту UknowSchool в Telegram. Код действует 30 минут и используется один раз. Логин и код входа в UknowApp сохраняются.
          </p>
          <div class="modal-actions">
            <Button variant="ghost" onClick={() => options.setCode(null)}>
              Закрыть
            </Button>
            <Button
              variant="primary"
              onClick={async () =>
                options.notify(
                  (await copyText(options.code.code)) ? "Код скопирован" : "Не удалось скопировать код",
                )
              }
            >
              <Copy />
              Скопировать
            </Button>
          </div>
        </Modal>
      )}
    </>
  );
}
