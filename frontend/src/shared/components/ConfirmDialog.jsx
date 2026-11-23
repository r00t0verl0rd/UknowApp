import Modal from "./Modal.jsx";
import Button from "./Button.jsx";
import IconButton from "./IconButton.jsx";
import { IconX as X } from "./Icons.jsx";

// Диалог подтверждения действия: заголовок, пояснение, «Отмена» и кнопка подтверждения.
// Пока выполняется действие (busy), закрытие и обе кнопки заблокированы.
export default function ConfirmDialog(options) {
  const confirmContent = () =>
    options.busy && options.busyLabel ? (
      options.busyLabel
    ) : (
      <>
        {options.icon}
        {options.confirmLabel}
      </>
    );
  return (
    <Modal
      onClose={options.onClose}
      closeOnBackdrop={!options.busy}
      class="confirm-delete-modal"
      role="alertdialog"
      labelledBy={options.titleId}
      describedBy={options.describedBy}
    >
      <div class="modal-head">
        <div>
          <div class="eyebrow">{options.eyebrow}</div>
          <h2 id={options.titleId}>{options.title}</h2>
        </div>
        {options.dismissible !== false && (
          <IconButton aria-label="Закрыть" disabled={options.busy} onClick={options.onClose}>
            <X />
          </IconButton>
        )}
      </div>
      <p class="hint" id={options.describedBy}>
        {options.children}
      </p>
      {options.preview}
      <div class="modal-actions">
        <Button variant="ghost" onClick={options.onClose} disabled={options.busy}>
          {options.cancelLabel ?? "Отмена"}
        </Button>
        <Button variant={options.tone ?? "danger"} onClick={options.onConfirm} disabled={options.busy}>
          {confirmContent()}
        </Button>
      </div>
    </Modal>
  );
}
