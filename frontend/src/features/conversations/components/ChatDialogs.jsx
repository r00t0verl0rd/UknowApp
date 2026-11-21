import Trash2 from "lucide-react/dist/esm/icons/trash-2.js";
import X from "lucide-react/dist/esm/icons/x.js";
import Modal from "../../../shared/components/Modal.jsx";
import Button from "../../../shared/components/Button.jsx";
import IconButton from "../../../shared/components/IconButton.jsx";
import FormField from "../../../shared/components/FormField.jsx";

export default function ChatDialogs({
  modal, setModal, users, createPersonalChat, creating, error,
  deleteMessageCandidate, selectedChat, deletingMessage,
  setDeleteMessageCandidate, confirmDeleteMessage,
}) {
  return <>
    {modal?.mode === "create-personal" && <Modal onClose={() => setModal(null)} closeOnBackdrop={!creating} className="create-participant-modal" labelledBy="personal-chat-title">
      <div className="modal-head"><div><div className="eyebrow">ЛИЧНЫЕ СООБЩЕНИЯ</div><h2 id="personal-chat-title">Создать диалог</h2></div><IconButton onClick={() => setModal(null)} disabled={creating} aria-label="Закрыть"><X/></IconButton></div>
      <form className="stack" onSubmit={event => {
        event.preventDefault();
        void createPersonalChat(Number(event.currentTarget.elements.participant.value));
      }}>
        <FormField label="Участник">
          <select name="participant" defaultValue="" required autoFocus disabled={creating}>
            <option value="" disabled>Выберите учителя или ученика</option>
            {users.filter(user => user.role === "teacher" || user.role === "student").map(user =>
              <option key={user.id} value={user.id}>
                {user.full_name} · {user.role === "teacher" ? "Учитель" : "Ученик"} · №{user.id}
              </option>
            )}
          </select>
        </FormField>
        {error && <p className="form-error" role="alert">{error}</p>}
        <div className="modal-actions"><Button variant="ghost" disabled={creating} onClick={() => setModal(null)}>Отмена</Button><Button type="submit" variant="primary" disabled={creating}>{creating ? "Открываем…" : "Создать диалог"}</Button></div>
      </form>
    </Modal>}

    {deleteMessageCandidate && <Modal onClose={() => setDeleteMessageCandidate(null)} closeOnBackdrop={!deletingMessage} className="confirm-delete-modal" role="alertdialog" labelledBy="delete-message-title">
        <div className="modal-head"><div><div className="eyebrow">УДАЛЕНИЕ СООБЩЕНИЯ</div><h2 id="delete-message-title">Удалить у всех?</h2></div><IconButton onClick={() => setDeleteMessageCandidate(null)} disabled={deletingMessage} aria-label="Закрыть"><X/></IconButton></div>
        <p className="hint">{selectedChat?.type === "personal" ? "Сообщение будет удалено из личного диалога UknowApp. Чужие сообщения удалить нельзя." : "Сообщение будет удалено из переписки UknowApp и предпринята попытка удалить его копии в Telegram у всех получателей. Чужие сообщения удалить нельзя."}</p>
        <div className="message-delete-preview">{deleteMessageCandidate.text || deleteMessageCandidate.metadata?.media?.file_name || "Вложение"}</div>
        <div className="modal-actions"><Button variant="ghost" onClick={() => setDeleteMessageCandidate(null)} disabled={deletingMessage}>Отмена</Button><Button variant="danger" onClick={confirmDeleteMessage} disabled={deletingMessage}>{deletingMessage ? "Удаляем…" : <><Trash2/>Удалить у всех</>}</Button></div>
      </Modal>}
  </>;
}
