import { Dynamic } from "@solidjs/web";
export default function EmptyState(options) {
  return (
    <div class={["empty-state", options.className ?? ""].filter(Boolean).join(" ")}>
      {options.icon && <Dynamic component={options.icon} />}
      {options.title && <b>{options.title}</b>}
      {options.description && <span>{options.description}</span>}
      {options.children}
    </div>
  );
}
