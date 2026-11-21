export default function EmptyState({ children, className = "", icon: Icon, title, description }) {
  return (
    <div className={["empty-state", className].filter(Boolean).join(" ")}>
      {Icon && <Icon />}
      {title && <b>{title}</b>}
      {description && <span>{description}</span>}
      {children}
    </div>
  );
}
