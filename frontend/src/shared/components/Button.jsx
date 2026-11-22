import { omit } from "solid-js";
const VARIANT_CLASSES = Object.freeze({
  primary: "primary",
  outline: "outline",
  ghost: "ghost",
  danger: "danger",
  disconnect: "disconnect",
});
const SIZE_CLASSES = Object.freeze({
  small: "small",
  compact: "compact",
});
export default function Button(options) {
  const props = omit(options, "variant", "size", "className", "type", "children");
  const classes = () =>
    ["btn", VARIANT_CLASSES[options.variant], SIZE_CLASSES[options.size], options.className ?? ""]
      .filter(Boolean)
      .join(" ");
  return (
    <button {...props} type={options.type ?? "button"} class={classes()}>
      {options.children}
    </button>
  );
}
