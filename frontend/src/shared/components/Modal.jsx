import { useEffect, useRef } from "react";
import { createPortal } from "react-dom";

export default function Modal({
  children, className = "", onClose, closeOnBackdrop = true,
  role = "dialog", labelledBy, describedBy, ariaModal = true,
}) {
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const handleKeyDown = event => {
      if (event.key === "Escape" && closeOnBackdrop) onCloseRef.current?.();
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [closeOnBackdrop]);

  const closeFromBackdrop = event => {
    if (event.target === event.currentTarget && closeOnBackdrop) onClose?.();
  };

  return createPortal(
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
    </div>,
    document.body,
  );
}
