import Check from "lucide-react/dist/esm/icons/check.js";
import Copy from "lucide-react/dist/esm/icons/copy.js";
import RefreshCw from "lucide-react/dist/esm/icons/refresh-cw.js";
import Trash2 from "lucide-react/dist/esm/icons/trash-2.js";
import X from "lucide-react/dist/esm/icons/x.js";
import Unlink from "lucide-react/dist/esm/icons/unlink.js";
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
    // Fall through to the browser clipboard fallback.
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
  try { copied = document.execCommand("copy"); } catch { copied = false; }
  textarea.remove();
  return copied;
}

export default function UserDialogs({
  modal, setModal, assign, teacherId, setTeacherId, allTeachers,
  studentId, setStudentId, allStudents, saveUser, name, setName,
  panelLogin, setPanelLogin, role, setRole, additionalInfo,
  setAdditionalInfo, telegramId, setTelegramId, users, savingUser,
  regeneratePanelAccessCode, removeUser, deleteCandidate, setDeleteCandidate,
  deletingUser, confirmRemoveUser, disconnectCandidate,
  setDisconnectCandidate, disconnectingTelegram, confirmDisconnectTelegram,
  issuedCredential, setIssuedCredential, notify, code, setCode,\n  unassignCandidate, setUnassignCandidate, unassigningStudent, confirmUnassignStudent,
}) {
  return <>
    {modal && modal.mode !== "create-personal" && <Modal onClose={() => setModal(null)} className={`${modal.mode === "create" ? "create-participant-modal" : modal.mode === "edit" ? "participant-profile-modal" : ""}`}>
      <div className="modal-head"><div><div className="eyebrow">{modal.mode === "create" ? "НОВЫЙ УЧАСТНИК" : modal.mode === "edit" ? "ПРОФИЛЬ УЧАСТНИКА" : "СВЯЗЬ УЧЕНИКА И УЧИТЕЛЯ"}</div><h2>{modal.mode === "create" ? "Добавить участника" : modal.mode === "edit" ? "Редактировать" : "Назначить ученика"}</h2></div><IconButton onClick={() => setModal(null)}><X/></IconButton></div>
      {modal.mode === "assign" ? <form className="stack" onSubmit={assign}>
        <FormField label="Учитель"><select value={teacherId} onChange={event => setTeacherId(event.target.value)} required>{allTeachers.map(teacher => <option value={teacher.id} key={teacher.id}>{teacher.full_name}</option>)}</select></FormField>
        <FormField label="Ученик"><select value={studentId} onChange={event => setStudentId(event.target.value)} required>{allStudents.map(student => <option value={student.id} key={student.id}>{student.full_name}</option>)}</select></FormField>
        <p className="hint">Если у ученика уже есть активное назначение, оно будет заменено новым.</p>
        <Button type="submit" variant="primary" disabled={!allStudents.length}>Создать связь</Button>
      </form> : <form className="stack" onSubmit={saveUser}>
        <FormField label="Имя и фамилия"><input value={name} onChange={event => { const nextName = event.target.value; setName(nextName); if (!panelLogin || panelLogin === name) setPanelLogin(nextName); }} minLength="2" maxLength="160" required autoFocus/></FormField>
        {role === "student" && <FormField label="Доп. инфо"><input value={additionalInfo} onChange={event => setAdditionalInfo(event.target.value)} maxLength="500"/></FormField>}
        <FormField label="Роль"><select value={role} onChange={event => setRole(event.target.value)}><option value="teacher">Учитель</option><option value="student">Ученик</option></select></FormField>
        <FormField label="Telegram ID"><input type="text" inputMode="numeric" pattern="[0-9]*" value={telegramId} onChange={event => setTelegramId(event.target.value)} /></FormField>
        {["teacher", "student"].includes(role) && <div className="panel-credentials-panel">
          <div className="panel-credential-row panel-login-edit-row">
            <label htmlFor="panel-web-login">Логин веб-панели</label>
            <input id="panel-web-login" value={panelLogin || name} onChange={event => setPanelLogin(event.target.value)} minLength="2" maxLength="160" required autoComplete="off" />
          </div>
          {modal.mode === "edit" && users.find(user => user.id === modal.id)?.role === role && <div className="panel-credential-row panel-access-row">
            <span>Код доступа</span>
            <div className="panel-access-value"><b>XXXX-XXXX</b><Button variant="outline" className="password-code-refresh" onClick={regeneratePanelAccessCode} disabled={savingUser} title="Старый код сразу перестанет действовать"><RefreshCw size={12}/>Обновить код</Button></div>
          </div>}
        </div>}
        {modal.mode === "edit" && role !== users.find(user => user.id === modal.id)?.role && <p className="hint">При смене роли активные назначения будут закрыты. История переписок сохранится.</p>}
        <div className="modal-actions"><Button type="submit" variant="primary" disabled={savingUser}>{savingUser ? "Сохраняем…" : <><Check/>Сохранить</>}</Button>{modal.mode === "edit" && <button type="button" className="user-action-btn danger-icon user-delete" onClick={() => removeUser(users.find(user => user.id === modal.id))} disabled={savingUser} title="Удалить пользователя" aria-label="Удалить пользователя"><Trash2 size={16}/></button>}</div>
      </form>}
    </Modal>}

    {deleteCandidate && <Modal onClose={() => setDeleteCandidate(null)} closeOnBackdrop={!deletingUser} className="confirm-delete-modal" role="alertdialog" labelledBy="delete-user-title">
        <div className="modal-head"><div><div className="eyebrow">УДАЛЕНИЕ УЧАСТНИКА</div><h2 id="delete-user-title">Удалить участника?</h2></div><IconButton onClick={() => setDeleteCandidate(null)} disabled={deletingUser} aria-label="Закрыть"><X/></IconButton></div>
        <p className="hint">Профиль «<b>{deleteCandidate.full_name}</b>», связанные переписки и сообщения будут удалены. Это действие нельзя отменить.</p>
        <div className="modal-actions"><Button variant="ghost" onClick={() => setDeleteCandidate(null)} disabled={deletingUser}>Отмена</Button><Button variant="danger" onClick={confirmRemoveUser} disabled={deletingUser}>{deletingUser ? "Удаляем…" : <><Trash2/>Удалить участника</>}</Button></div>
      </Modal>}

    {unassignCandidate && <Modal onClose={() => setUnassignCandidate(null)} closeOnBackdrop={!unassigningStudent} className="confirm-delete-modal" role="alertdialog" labelledBy="unassign-student-title">
        <div className="modal-head"><div><div className="eyebrow">ОТВЯЗКА УЧЕНИКА</div><h2 id="unassign-student-title">Отвязать ученика?</h2></div><IconButton onClick={() => setUnassignCandidate(null)} disabled={unassigningStudent} aria-label="Закрыть"><X/></IconButton></div>
        <p className="hint">Ученик «<b>{unassignCandidate.full_name}</b>» будет отвязан от учителя и появится в разделе «Ученики без учителя». Активная переписка с учителем закроется, история сообщений сохранится.</p>
        <div className="modal-actions"><Button variant="ghost" onClick={() => setUnassignCandidate(null)} disabled={unassigningStudent}>Отмена</Button><Button variant="danger" onClick={confirmUnassignStudent} disabled={unassigningStudent}>{unassigningStudent ? "Отвязываем…" : <><Unlink/>Отвязать ученика</>}</Button></div>
      </Modal>}

    {disconnectCandidate && <Modal onClose={() => setDisconnectCandidate(null)} closeOnBackdrop={!disconnectingTelegram} className="confirm-delete-modal" role="alertdialog" labelledBy="disconnect-telegram-title">
        <div className="modal-head"><div><div className="eyebrow">ОТКЛЮЧЕНИЕ TELEGRAM</div><h2 id="disconnect-telegram-title">Отключить Telegram?</h2></div><IconButton onClick={() => setDisconnectCandidate(null)} disabled={disconnectingTelegram} aria-label="Закрыть"><X/></IconButton></div>
        <p className="hint">Отключить Telegram у пользователя «<b>{disconnectCandidate.full_name}</b>»? Профиль и история переписки останутся в системе. Отправлять и получать сообщения через бота он не сможет до повторного подключения.</p>
        <div className="modal-actions"><Button variant="ghost" onClick={() => setDisconnectCandidate(null)} disabled={disconnectingTelegram}>Отмена</Button><Button variant="danger" onClick={confirmDisconnectTelegram} disabled={disconnectingTelegram}>{disconnectingTelegram ? "Отключаем…" : "Отключить Telegram"}</Button></div>
      </Modal>}

    {issuedCredential && <Modal onClose={() => setIssuedCredential(null)} className="credential-modal">
      <div className="modal-head"><div><div className="eyebrow">{issuedCredential.role === "student" ? "ЕДИНЫЙ КОД ДОСТУПА УЧЕНИКА" : "ЕДИНЫЙ КОД ДОСТУПА УЧИТЕЛЯ"}</div><h2>{issuedCredential.full_name}</h2></div><IconButton onClick={() => setIssuedCredential(null)}><X/></IconButton></div>
      <div className="credential-field"><div className="credential-field-label">Логин</div><div className="credential-field-value"><b>{issuedCredential.username}</b><IconButton onClick={async () => notify(await copyText(issuedCredential.username) ? "Логин скопирован" : "Не удалось скопировать логин")} aria-label="Скопировать логин"><Copy size={16}/></IconButton></div></div>
      <div className="credential-field credential-field-code"><div className="credential-field-label">Код доступа</div><div className="credential-field-value"><b>{issuedCredential.code}</b><IconButton onClick={async () => notify(await copyText(issuedCredential.code) ? "Код доступа скопирован" : "Не удалось скопировать код доступа")} aria-label="Скопировать код доступа"><Copy size={16}/></IconButton></div></div>
      <div className="modal-actions credential-actions"><Button variant="primary" onClick={async () => notify(await copyText("Логин: " + issuedCredential.username + "\nКод доступа: " + issuedCredential.code) ? "Данные для входа скопированы" : "Не удалось скопировать данные")}><Copy size={16}/>Скопировать данные</Button></div>
    </Modal>}

    {code && <Modal onClose={() => setCode(null)}>
      <div className="modal-head"><div><div className="eyebrow">ПОДКЛЮЧЕНИЕ TELEGRAM</div><h2>{code.full_name}</h2></div><IconButton onClick={() => setCode(null)}><X/></IconButton></div>
      <div className="invite-code">{code.code}</div>
      <p className="hint">{code.shared_access ? `Это единый код ${code.role === "student" ? "ученика" : "учителя"}: он подходит для входа в веб-панель вместе с логином и для подключения Telegram. Он действует, пока администратор не заменит его новым.` : "Передайте этот код ученику для подключения Telegram. Он действует до первого успешного подключения и используется один раз."}</p>
      <div className="modal-actions"><Button variant="ghost" onClick={() => setCode(null)}>Закрыть</Button><Button variant="primary" onClick={async () => notify(await copyText(code.code) ? "Код скопирован" : "Не удалось скопировать код")}><Copy/>Скопировать</Button></div>
    </Modal>}
  </>;
}
