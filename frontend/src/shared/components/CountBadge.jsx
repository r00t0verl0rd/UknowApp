export default function CountBadge({
  value,
  label,
  title,
  className = "",
  unread = false,
  hideWhenZero = false,
  max = 99,
  as = "span",
}) {
  const count = Math.max(0, Number(value) || 0);
  if (hideWhenZero && count === 0) return null;

  const Element = as === "b" ? "b" : "span";
  const formatted = count > max ? `${max}+` : count;
  const accessibleLabel = label ? `${formatted} ${label}` : undefined;

  return (
    <Element
      className={["chat-tab-count", unread && "chat-tab-count--unread", className].filter(Boolean).join(" ")}
      title={title}
      aria-label={accessibleLabel}
    >
      {formatted}
    </Element>
  );
}
