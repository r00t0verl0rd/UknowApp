import CircleAlert from "lucide-react/dist/esm/icons/circle-alert.js";
import X from "lucide-react/dist/esm/icons/x.js";
import Check from "lucide-react/dist/esm/icons/check.js";
import { useId, useLayoutEffect, useRef } from "react";
import { createPortal } from "react-dom";
import IconButton from "./IconButton.jsx";

// Ошибки открываются через showModal(), подтверждения — через show() без
// блокировки интерфейса. Оба уведомления используют нативный <dialog>.
export default function AppToast({ message, onDismiss }) {
  const dialogRef = useRef(null);
  const headingId = useId();
  const isError = Boolean(onDismiss);

  useLayoutEffect(() => {
    const dialog = dialogRef.current;
    if (!message || !dialog) return undefined;
    if (dialog.open) dialog.close();
    if (isError) dialog.showModal();
    else dialog.show();
    return () => { if (dialog.open) dialog.close(); };
  }, [message, isError]);

  if (!message) return null;

  return createPortal(
    <dialog
      ref={dialogRef}
      className={["modal", "native-dialog", "native-feedback-dialog", isError ? "native-feedback-error" : "native-feedback-success"].join(" ")}
      role={isError ? "alertdialog" : "dialog"}
      aria-modal={isError ? "true" : undefined}
      aria-labelledby={headingId}
      aria-live={isError ? "assertive" : "polite"}
      onCancel={event => {
        event.preventDefault();
        onDismiss?.();
      }}
    >
      <div className="native-feedback-content">
        {isError ? <CircleAlert size={21} aria-hidden="true"/> : <Check size={20} aria-hidden="true"/>}
        <div className="native-feedback-copy">
          <h2 id={headingId}>{isError ? "Ошибка" : "Готово"}</h2>
          <p className="toast-message">{message}</p>
        </div>
        {isError && <IconButton size="large" className="toast-close"
          aria-label="Закрыть уведомление об ошибке" onClick={onDismiss}>
          <X aria-hidden="true"/>
        </IconButton>}
      </div>
    </dialog>,
    document.body,
  );
}
