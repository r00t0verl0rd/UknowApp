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
          className={`${options.modal.mode === "create" ? "create-participant-modal" : options.modal.mode === "edit" ? "participant-profile-modal" : ""}`}
        >
          <div class="modal-head">
            <div>
              <div class="eyebrow">
                {options.modal.mode === "create"
                  ? "НОВЫЙ УЧАСТНИК"
                  : options.modal.mode === "edit"
                    ? "ПРОФИЛЬ УЧАСТНИКА"
                    : "СВЯЗЬ УЧЕНИКА И УЧИТЕЛЯ"}
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
              <p class="hint">Если у ученика уже есть активное назначение, оно будет заменено новым.</p>
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
                  {options.modal.mode === "edit" &&
                    options.users.find((user) => user.id === options.modal.id)?.role === options.role && (
                      <div class="panel-credential-row panel-access-row">
                        <span>Код доступа</span>
                        <div class="panel-access-value">
                          <b>XXXX-XXXX</b>
                          <Button
                            variant="outline"
                            className="password-code-refresh"
                            onClick={() => setConfirmNewCode(true)}
                            disabled={options.savingUser}
                            title="Старый код сразу перестанет действовать"
                          >
                            <RefreshCw size={16} />
                            Новый код
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
                    className="user-action-btn danger-icon user-delete"
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
        <Modal
          onClose={() => setConfirmNewCode(false)}
          closeOnBackdrop={!options.savingUser}
          className="confirm-delete-modal"
          role="alertdialog"
          labelledBy="new-access-code-title"
        >
          <div class="modal-head">
            <div>
              <div class="eyebrow">НОВЫЙ КОД ДОСТУПА</div>
              <h2 id="new-access-code-title">Выдать новый код?</h2>
            </div>
            <IconButton
              aria-label="Закрыть"
              disabled={options.savingUser}
              onClick={() => setConfirmNewCode(false)}
            >
              <X />
            </IconButton>
          </div>
          <p class="hint">
            После выдачи нового кода прежний сразу перестанет действовать. Новый код появится в отдельном
            окне, откуда его можно скопировать.
          </p>
          <div class="modal-actions">
            <Button variant="ghost" onClick={() => setConfirmNewCode(false)} disabled={options.savingUser}>
              Отмена
            </Button>
            <Button
              variant="primary"
              disabled={options.savingUser}
              onClick={async () => {
                setConfirmNewCode(false);
                await options.regeneratePanelAccessCode();
              }}
            >
              Выдать код
            </Button>
          </div>
        </Modal>
      )}

      {options.deleteCandidate && (
        <Modal
          onClose={() => options.setDeleteCandidate(null)}
          closeOnBackdrop={!options.deletingUser}
          className="confirm-delete-modal"
          role="alertdialog"
          labelledBy="delete-user-title"
        >
          <div class="modal-head">
            <div>
              <div class="eyebrow">УДАЛЕНИЕ УЧАСТНИКА</div>
              <h2 id="delete-user-title">Удалить участника?</h2>
            </div>
            <IconButton
              onClick={() => options.setDeleteCandidate(null)}
              disabled={options.deletingUser}
              aria-label="Закрыть"
            >
              <X />
            </IconButton>
          </div>
          <p class="hint">
            Профиль «<b>{options.deleteCandidate.full_name}</b>», связанные переписки и сообщения будут
            удалены. Это действие нельзя отменить.
          </p>
          <div class="modal-actions">
            <Button
              variant="ghost"
              onClick={() => options.setDeleteCandidate(null)}
              disabled={options.deletingUser}
            >
              Отмена
            </Button>
            <Button variant="danger" onClick={options.confirmRemoveUser} disabled={options.deletingUser}>
              {options.deletingUser ? (
                "Удаляем…"
              ) : (
                <>
                  <Trash2 />
                  Удалить участника
                </>
              )}
            </Button>
          </div>
        </Modal>
      )}

      {options.unassignCandidate && (
        <Modal
          onClose={() => options.setUnassignCandidate(null)}
          closeOnBackdrop={!options.unassigningStudent}
          className="confirm-delete-modal"
          role="alertdialog"
          labelledBy="unassign-student-title"
        >
          <div class="modal-head">
            <div>
              <div class="eyebrow">ОТВЯЗКА УЧЕНИКА</div>
              <h2 id="unassign-student-title">Отвязать ученика?</h2>
            </div>
            <IconButton
              onClick={() => options.setUnassignCandidate(null)}
              disabled={options.unassigningStudent}
              aria-label="Закрыть"
            >
              <X />
            </IconButton>
          </div>
          <p class="hint">
            Ученик «<b>{options.unassignCandidate.full_name}</b>» будет отвязан от учителя и появится в
            разделе «Ученики без учителя». Активная переписка с учителем закроется, история сообщений
            сохранится.
          </p>
          <div class="modal-actions">
            <Button
              variant="ghost"
              onClick={() => options.setUnassignCandidate(null)}
              disabled={options.unassigningStudent}
            >
              Отмена
            </Button>
            <Button
              variant="danger"
              onClick={options.confirmUnassignStudent}
              disabled={options.unassigningStudent}
            >
              {options.unassigningStudent ? (
                "Отвязываем…"
              ) : (
                <>
                  <Unlink />
                  Отвязать ученика
                </>
              )}
            </Button>
          </div>
        </Modal>
      )}

      {options.disconnectCandidate && (
        <Modal
          onClose={() => options.setDisconnectCandidate(null)}
          closeOnBackdrop={!options.disconnectingTelegram}
          className="confirm-delete-modal"
          role="alertdialog"
          labelledBy="disconnect-telegram-title"
        >
          <div class="modal-head">
            <div>
              <div class="eyebrow">ОТКЛЮЧЕНИЕ TELEGRAM</div>
              <h2 id="disconnect-telegram-title">Отключить Telegram?</h2>
            </div>
            <IconButton
              onClick={() => options.setDisconnectCandidate(null)}
              disabled={options.disconnectingTelegram}
              aria-label="Закрыть"
            >
              <X />
            </IconButton>
          </div>
          <p class="hint">
            Отключить Telegram у пользователя «<b>{options.disconnectCandidate.full_name}</b>»? Профиль и
            история переписки останутся в системе. Отправлять и получать сообщения через бота он не сможет до
            повторного подключения.
          </p>
          <div class="modal-actions">
            <Button
              variant="ghost"
              onClick={() => options.setDisconnectCandidate(null)}
              disabled={options.disconnectingTelegram}
            >
              Отмена
            </Button>
            <Button
              variant="danger"
              onClick={options.confirmDisconnectTelegram}
              disabled={options.disconnectingTelegram}
            >
              {options.disconnectingTelegram ? "Отключаем…" : "Отключить Telegram"}
            </Button>
          </div>
        </Modal>
      )}

      {options.issuedCredential && (
        <Modal onClose={() => options.setIssuedCredential(null)} className="credential-modal">
          <div class="modal-head">
            <div>
              <div class="eyebrow">
                {options.issuedCredential.role === "student"
                  ? "ЕДИНЫЙ КОД ДОСТУПА УЧЕНИКА"
                  : "ЕДИНЫЙ КОД ДОСТУПА УЧИТЕЛЯ"}
              </div>
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
            <div class="credential-field-label">Код доступа</div>
            <div class="credential-field-value">
              <b>{options.issuedCredential.code}</b>
              <IconButton
                onClick={async () =>
                  options.notify(
                    (await copyText(options.issuedCredential.code))
                      ? "Код доступа скопирован"
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
                      "\nКод доступа: " +
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
              <div class="eyebrow">ПОДКЛЮЧЕНИЕ TELEGRAM</div>
              <h2>{options.code.full_name}</h2>
            </div>
            <IconButton onClick={() => options.setCode(null)}>
              <X />
            </IconButton>
          </div>
          <div class="invite-code">{options.code.code}</div>
          <p class="hint">
            {options.code.shared_access
              ? `Это единый код ${options.code.role === "student" ? "ученика" : "учителя"}: он подходит для входа в веб-панель вместе с логином и для подключения Telegram. Он действует, пока администратор не заменит его новым.`
              : "Передайте этот код ученику для подключения Telegram. Он действует до первого успешного подключения и используется один раз."}
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
