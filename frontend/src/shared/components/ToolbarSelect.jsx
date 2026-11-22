import ChevronDown from "lucide-react/dist/esm/icons/chevron-down.js";

// Нативный select с единым оформлением для Safari и других браузеров.
export default function ToolbarSelect({ className = "", selectClassName = "", children, ...props }) {
  return (
    <span className={["ui-toolbar-select", className].filter(Boolean).join(" ")}>
      <select {...props} className={["ui-toolbar-control", "ui-toolbar-select-native", selectClassName].filter(Boolean).join(" ")}>
        {children}
      </select>
      <ChevronDown className="ui-toolbar-select-chevron" size={14} aria-hidden="true" />
    </span>
  );
}
