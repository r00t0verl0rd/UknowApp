export default function Modal({
  children,
  className = "",
  onClose,
  closeOnBackdrop = true,
  role = "dialog",
  labelledBy,
  describedBy,
  ariaModal = true,
}) {
  const closeFromBackdrop = event => {
    if (event.target === event.currentTarget && closeOnBackdrop) onClose?.();
  };

  return (
    <div className="overlay" onMouseDown={closeFromBackdrop}>
      <section
        className={["modal", className].filter(Boolean).join(" ")}
        role={role}
        aria-modal={ariaModal ? "true" : undefined}
        aria-labelledby={labelledBy}
        aria-describedby={describedBy}
        onMouseDown={event => event.stopPropagation()}
      >
        {children}
      </section>
    </div>
  );
}
