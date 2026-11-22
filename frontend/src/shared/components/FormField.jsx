import { omit } from "solid-js";
export default function FormField(options) {
  const props = omit(options, "label", "htmlFor", "hint", "className", "children");
  return (
    <label {...props} for={options.htmlFor} class={(options.className ?? "") || undefined}>
      <span>{options.label}</span>
      {options.children}
      {options.hint && <small class="hint">{options.hint}</small>}
    </label>
  );
}
