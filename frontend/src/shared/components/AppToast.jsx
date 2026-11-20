import Check from "lucide-react/dist/esm/icons/check.js";

export default function AppToast({ message }) {
  return message ? <div className="toast" role="status"><Check/>{message}</div> : null;
}
