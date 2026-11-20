import Trash2 from "lucide-react/dist/esm/icons/trash-2.js";
import X from "lucide-react/dist/esm/icons/x.js";

export default function ChatDialogs({
  modal, setModal, users, createPersonalChat, error, setError,
  deleteMessageCandidate, selectedChat, deletingMessage,
  setDeleteMessageCandidate, confirmDeleteMessage,
}) {
  return <>
    {modal?.mode === "create-personal" && <div className="overlay" onMouseDown={() => setModal(null)}><section className="modal create-participant-modal" role="dialog" aria-modal="true" aria-labelledby="personal-chat-title" onMouseDown={event => event.stopPropagation()}>
      <div className="modal-head"><div><div className="eyebrow">ЛИЧНЫЕ СООБЩЕНИЯ</div><h2 id="personal-chat-title">Создать диалог</h2></div><button type="button" className="icon-btn" onClick={() => setModal(null)} aria-label="Закрыть"><X/></button></div>
      <form className="stack" onSubmit={event => {
        event.preventDefault();
        const value = event.currentTarget.elements.participant.value.trim().toLocaleLowerCase("ru");
        const selected = users.find(user => ["teacher", "student"].includes(user.role) && user.full_name.trim().toLocaleLowerCase("ru") === value);
        if (selected) void createPersonalChat(selected.id);
        else setError("Выберите участника из списка учителей и учеников");
      }}>
        <label>Участник<input name="participant" list="personal-participant-options" placeholder="Начните вводить имя" autoComplete="off" autoFocus required/></label>
        <datalist id="personal-participant-options">{users.filter(user => ["teacher", "student"].includes(user.role)).map(user => <option value={user.full_name} key={user.id}>{user.role === "teacher" ? "Учитель" : "Ученик"}</option>)}</datalist>
        <p className="hint">Начните вводить имя и выберите нужного участника. Личный диалог будет доступен только внутри UknowApp.</p>
        {error && <p className="form-error" role="alert">{error}</p>}
        <div className="modal-actions"><button type="button" className="btn ghost" onClick={() => setModal(null)}>Отмена</button><button type="submit" className="btn primary">Создать диалог</button></div>
      </form>
    </section></div>}

    {deleteMessageCandidate && <div className="overlay" onMouseDown={() => !deletingMessage && setDeleteMessageCandidate(null)}>
      <section className="modal confirm-delete-modal" role="alertdialog" aria-modal="true" aria-labelledby="delete-message-title" onMouseDown={event => event.stopPropagation()}>
        <div className="modal-head"><div><div className="eyebrow">УДАЛЕНИЕ СООБЩЕНИЯ</div><h2 id="delete-message-title">Удалить у всех?</h2></div><button className="icon-btn" type="button" onClick={() => setDeleteMessageCandidate(null)} disabled={deletingMessage} aria-label="Закрыть"><X/></button></div>
        <p className="hint">{selectedChat?.type === "personal" ? "Сообщение будет удалено из личного диалога UknowApp. Чужие сообщения удалить нельзя." : "Сообщение будет удалено из переписки UknowApp и предпринята попытка удалить его копии в Telegram у всех получателей. Чужие сообщения удалить нельзя."}</p>
        <div className="message-delete-preview">{deleteMessageCandidate.text || deleteMessageCandidate.metadata?.media?.file_name || "Вложение"}</div>
        <div className="modal-actions"><button type="button" className="btn ghost" onClick={() => setDeleteMessageCandidate(null)} disabled={deletingMessage}>Отмена</button><button type="button" className="btn danger" onClick={confirmDeleteMessage} disabled={deletingMessage}>{deletingMessage ? "Удаляем…" : <><Trash2/>Удалить у всех</>}</button></div>
      </section>
    </div>}
  </>;
}
