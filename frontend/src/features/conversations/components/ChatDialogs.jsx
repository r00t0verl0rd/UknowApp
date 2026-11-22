import { For } from "solid-js";
import { IconTrash2 as Trash2, IconX as X } from "../../../shared/components/Icons.jsx";
import Modal from "../../../shared/components/Modal.jsx";
import Button from "../../../shared/components/Button.jsx";
import IconButton from "../../../shared/components/IconButton.jsx";
import FormField from "../../../shared/components/FormField.jsx";
export default function ChatDialogs(options) {
  return (
    <>
      {options.modal?.mode === "create-personal" && (
        <Modal
          onClose={() => options.setModal(null)}
          closeOnBackdrop={!options.creating}
          class="create-participant-modal"
          labelledBy="personal-chat-title"
        >
          <div class="modal-head">
            <div>
              <div class="eyebrow">ЛИЧНЫЕ СООБЩЕНИЯ</div>
              <h2 id="personal-chat-title">Создать диалог</h2>
            </div>
            <IconButton
              onClick={() => options.setModal(null)}
              disabled={options.creating}
              aria-label="Закрыть"
            >
              <X />
            </IconButton>
          </div>
          <form
            class="stack"
            onSubmit={(event) => {
              event.preventDefault();
              void options.createPersonalChat(Number(event.currentTarget.elements.participant.value));
            }}
          >
            <FormField label="Участник">
              <select name="participant" required autofocus disabled={options.creating}>
                <option value="" disabled selected>
                  Выберите учителя или ученика
                </option>
                <For
                  each={options.users.filter((user) => user.role === "teacher" || user.role === "student")}
                >
                  {(user) => (
                    <option value={user.id}>
                      {user.full_name} · {user.role === "teacher" ? "Учитель" : "Ученик"} · №{user.id}
                    </option>
                  )}
                </For>
              </select>
            </FormField>
            <div class="modal-actions">
              <Button variant="ghost" disabled={options.creating} onClick={() => options.setModal(null)}>
                Отмена
              </Button>
              <Button type="submit" variant="primary" disabled={options.creating}>
                {options.creating ? "Открываем…" : "Создать диалог"}
              </Button>
            </div>
          </form>
        </Modal>
      )}

      {options.deleteMessageCandidate && (
        <Modal
          onClose={() => options.setDeleteMessageCandidate(null)}
          closeOnBackdrop={!options.deletingMessage}
          class="confirm-delete-modal"
          role="alertdialog"
          labelledBy="delete-message-title"
        >
          <div class="modal-head">
            <div>
              <div class="eyebrow">УДАЛЕНИЕ СООБЩЕНИЯ</div>
              <h2 id="delete-message-title">Удалить у всех?</h2>
            </div>
            <IconButton
              onClick={() => options.setDeleteMessageCandidate(null)}
              disabled={options.deletingMessage}
              aria-label="Закрыть"
            >
              <X />
            </IconButton>
          </div>
          <p class="hint">
            {options.selectedChat?.type === "personal"
              ? "Сообщение будет удалено из личного диалога UknowApp. Чужие сообщения удалить нельзя."
              : "Сообщение будет удалено из переписки UknowApp и предпринята попытка удалить его копии в Telegram у всех получателей. Чужие сообщения удалить нельзя."}
          </p>
          <div class="message-delete-preview">
            {options.deleteMessageCandidate.text ||
              options.deleteMessageCandidate.metadata?.media?.file_name ||
              "Вложение"}
          </div>
          <div class="modal-actions">
            <Button
              variant="ghost"
              onClick={() => options.setDeleteMessageCandidate(null)}
              disabled={options.deletingMessage}
            >
              Отмена
            </Button>
            <Button
              variant="danger"
              onClick={options.confirmDeleteMessage}
              disabled={options.deletingMessage}
            >
              {options.deletingMessage ? (
                "Удаляем…"
              ) : (
                <>
                  <Trash2 />
                  Удалить у всех
                </>
              )}
            </Button>
          </div>
        </Modal>
      )}
    </>
  );
}
