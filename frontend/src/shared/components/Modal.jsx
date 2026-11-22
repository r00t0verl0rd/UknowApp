import { useId, useLayoutEffect, useRef } from "react";
import { createPortal } from "react-dom";

// HTMLDialogElement управляет фокусом, Escape, блокировкой фона и top layer.
// Все окна приложения используют один нативный браузерный диалог.
export default function Modal({
  children, className = "", onClose, closeOnBackdrop = true,
  role = "dialog", labelledBy, describedBy, ariaModal = true,
}) {
  const dialogRef = useRef(null);
  const onCloseRef = useRef(onClose);
  const fallbackTitleId = useId();
  onCloseRef.current = onClose;

  useLayoutEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return undefined;
    if (!dialog.open) dialog.showModal();

    // Для старых окон без aria-labelledby используем их видимый h2.
    if (!labelledBy) {
      const heading = dialog.querySelector(".modal-head h2");
      if (heading && !heading.id) heading.id = fallbackTitleId;
    }

    return () => {
      if (dialog.open) dialog.close();
    };
  }, [fallbackTitleId, labelledBy]);

  const requestClose = () => {
    if (closeOnBackdrop) onCloseRef.current?.();
  };

  const handleCancel = event => {
    // Когда идёт сохранение или удаление, запретить Escape и закрытие фона.
    event.preventDefault();
    requestClose();
  };

  const handleBackdropClick = event => {
    if (event.target !== event.currentTarget || !closeOnBackdrop) return;
    const bounds = event.currentTarget.getBoundingClientRect();
    const outside = event.clientX < bounds.left || event.clientX > bounds.right
      || event.clientY < bounds.top || event.clientY > bounds.bottom;
    if (outside) requestClose();
  };

  return createPortal(
    <dialog ref={dialogRef}
      className={["modal", "native-dialog", className].filter(Boolean).join(" ")}
      role={role}
      aria-modal={ariaModal ? "true" : undefined}
      aria-labelledby={labelledBy || fallbackTitleId}
      aria-describedby={describedBy}
      onCancel={handleCancel}
      onClick={handleBackdropClick}
    >
      {children}
    </dialog>,
    document.body,
  );
}
