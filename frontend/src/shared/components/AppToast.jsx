import CircleX from "lucide-react/dist/esm/icons/circle-x.js";
import X from "lucide-react/dist/esm/icons/x.js";
import { createPortal } from "react-dom";
import Check from "lucide-react/dist/esm/icons/check.js";

export default function AppToast({ message, onDismiss }) {
  return message ? createPortal(
    <div className={onDismiss ? "toast toast-error" : "toast"} role={onDismiss ? "alert" : "status"}>
      {onDismiss ? <CircleX aria-hidden="true"/> : <Check aria-hidden="true"/>}
      <span>{message}</span>
      {onDismiss && <button type="button" aria-label="Закрыть уведомление об ошибке" onClick={onDismiss}><X/></button>}
    </div>,
    document.body,
  ) : null;
}
