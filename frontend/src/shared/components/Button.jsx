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

export default function Button({
  variant,
  size,
  className = "",
  type = "button",
  children,
  ...props
}) {
  const classes = [
    "btn",
    VARIANT_CLASSES[variant],
    SIZE_CLASSES[size],
    className,
  ].filter(Boolean).join(" ");

  return <button {...props} type={type} className={classes}>{children}</button>;
}
