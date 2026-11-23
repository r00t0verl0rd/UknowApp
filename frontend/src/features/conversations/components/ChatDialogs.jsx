import { For } from "solid-js";
import { IconTrash2 as Trash2, IconX as X } from "../../../shared/components/Icons.jsx";
import Modal from "../../../shared/components/Modal.jsx";
import ConfirmDialog from "../../../shared/components/ConfirmDialog.jsx";
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
        <ConfirmDialog
          eyebrow="УДАЛЕНИЕ СООБЩЕНИЯ"
          title="Удалить у всех?"
          titleId="delete-message-title"
          busy={options.deletingMessage}
          icon={<Trash2 />}
          confirmLabel="Удалить у всех"
          busyLabel="Удаляем…"
          onClose={() => options.setDeleteMessageCandidate(null)}
          onConfirm={options.confirmDeleteMessage}
          preview={
            <div class="message-delete-preview">
              {options.deleteMessageCandidate.text ||
                options.deleteMessageCandidate.metadata?.media?.file_name ||
                "Вложение"}
            </div>
          }
        >
          {options.selectedChat?.type === "personal"
            ? "Сообщение будет удалено из личного диалога UknowApp. Чужие сообщения удалить нельзя."
            : "Сообщение будет удалено из переписки UknowApp и предпринята попытка удалить его копии в Telegram у всех получателей. Чужие сообщения удалить нельзя."}
        </ConfirmDialog>
      )}
    </>
  );
}
