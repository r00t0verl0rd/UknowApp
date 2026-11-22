import { omit } from "solid-js";
// Нативный браузерный select: системное меню и управление с клавиатуры.
// Обёртка нужна только для общего размера полей в панелях.
export default function ToolbarSelect(options) {
  const props = omit(options, "className", "selectClassName", "children");
  return (
    <span class={["ui-toolbar-select", options.className ?? ""].filter(Boolean).join(" ")}>
      <select
        {...props}
        class={["ui-toolbar-control", "ui-toolbar-select-native", options.selectClassName ?? ""]
          .filter(Boolean)
          .join(" ")}
      >
        {options.children}
      </select>
    </span>
  );
}
