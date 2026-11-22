import CircleAlert from "lucide-react/dist/esm/icons/circle-alert.js";
import X from "lucide-react/dist/esm/icons/x.js";
import { createPortal } from "react-dom";
import Check from "lucide-react/dist/esm/icons/check.js";
import IconButton from "./IconButton.jsx";

export default function AppToast({ message, onDismiss }) {
  return message ? createPortal(
    <div className={onDismiss ? "toast toast-error" : "toast"} role={onDismiss ? "alert" : "status"}>
      {onDismiss ? <CircleAlert size={18} aria-hidden="true"/> : <Check size={16} aria-hidden="true"/>}
      <span className="toast-message">{message}</span>
      {onDismiss && <IconButton size="large" className="toast-close" aria-label="Закрыть уведомление об ошибке" onClick={onDismiss}><X aria-hidden="true"/></IconButton>}
    </div>,
    document.body,
  ) : null;
}
