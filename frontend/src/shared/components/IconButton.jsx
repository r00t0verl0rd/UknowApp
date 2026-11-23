import { omit } from "solid-js";
// Единая кнопка-иконка для карточек, списков, диалогов и панелей.
export default function IconButton(options) {
  const props = omit(options, "class", "tone", "size", "type", "children");
  const classes = () =>
    [
      "icon-btn",
      "ui-icon-button",
      (options.tone ?? "neutral") === "danger" && "ui-icon-button--danger",
      (options.tone ?? "neutral") === "student" && "ui-icon-button--student",
      (options.size ?? "default") !== "default" && `ui-icon-button--${options.size ?? "default"}`,
      options.class ?? "",
    ]
      .filter(Boolean)
      .join(" ");
  return (
    <button {...props} type={options.type ?? "button"} class={classes()}>
      {options.children}
    </button>
  );
}
