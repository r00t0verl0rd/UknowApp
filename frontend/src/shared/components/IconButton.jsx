// Единая кнопка-иконка для карточек, списков, диалогов и панелей.
export default function IconButton({
  className = "",
  tone = "neutral",
  size = "default",
  type = "button",
  children,
  ...props
}) {
  const classes = [
    "icon-btn",
    "ui-icon-button",
    tone === "danger" && "ui-icon-button--danger",
    size !== "default" && `ui-icon-button--${size}`,
    className,
  ].filter(Boolean).join(" ");

  return <button {...props} type={type} className={classes}>{children}</button>;
}
