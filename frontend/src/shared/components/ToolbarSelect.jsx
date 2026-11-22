// Нативный браузерный select: системное меню и управление с клавиатуры.
// Обёртка нужна только для общего размера полей в панелях.
export default function ToolbarSelect({ className = "", selectClassName = "", children, ...props }) {
  return (
    <span className={["ui-toolbar-select", className].filter(Boolean).join(" ")}>
      <select {...props} className={["ui-toolbar-control", "ui-toolbar-select-native", selectClassName].filter(Boolean).join(" ")}>
        {children}
      </select>
    </span>
  );
}
