import { Portal } from "@solidjs/web";
import { createUniqueId, createEffect } from "solid-js";
// HTMLDialogElement управляет фокусом, Escape, блокировкой фона и top layer.
// Все окна приложения используют один нативный браузерный диалог.
export default function Modal(options) {
  let dialogRef = null;
  const fallbackTitleId = createUniqueId();
  createEffect(
    () => [fallbackTitleId, options.labelledBy],
    () => {
      const dialog = dialogRef;
      if (!dialog) return undefined;
      if (!dialog.open) dialog.showModal();

      // Для старых окон без aria-labelledby используем их видимый h2.
      if (!options.labelledBy) {
        const heading = dialog.querySelector(".modal-head h2");
        if (heading && !heading.id) heading.id = fallbackTitleId;
      }
      return () => {
        if (dialog.open) dialog.close();
      };
    },
  );
  const requestClose = () => {
    if (options.closeOnBackdrop ?? true) options.onClose?.();
  };
  const handleCancel = (event) => {
    // Когда идёт сохранение или удаление, запретить Escape и закрытие фона.
    event.preventDefault();
    requestClose();
  };
  const handleBackdropClick = (event) => {
    if (event.target !== event.currentTarget || !(options.closeOnBackdrop ?? true)) return;
    const bounds = event.currentTarget.getBoundingClientRect();
    const outside =
      event.clientX < bounds.left ||
      event.clientX > bounds.right ||
      event.clientY < bounds.top ||
      event.clientY > bounds.bottom;
    if (outside) requestClose();
  };
  return (
    <Portal mount={document.body}>
      <dialog
        ref={dialogRef}
        class={["modal", "native-dialog", options.className ?? ""].filter(Boolean).join(" ")}
        role={options.role ?? "dialog"}
        aria-modal={(options.ariaModal ?? true) ? "true" : undefined}
        aria-labelledby={options.labelledBy || fallbackTitleId}
        aria-describedby={options.describedBy}
        onCancel={handleCancel}
        onClick={handleBackdropClick}
      >
        {options.children}
      </dialog>
    </Portal>
  );
}
