export default function IconButton({
  className = "",
  type = "button",
  children,
  ...props
}) {
  return (
    <button {...props} type={type} className={["icon-btn", className].filter(Boolean).join(" ")}>
      {children}
    </button>
  );
}
