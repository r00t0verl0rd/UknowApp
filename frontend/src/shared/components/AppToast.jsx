import { createPortal } from "react-dom";
import Check from "lucide-react/dist/esm/icons/check.js";

export default function AppToast({ message }) {
  return message ? createPortal(
    <div className="toast" role="status" aria-live="polite"><Check/>{message}</div>,
    document.body,
  ) : null;
}
