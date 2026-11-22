import { Portal } from "@solidjs/web";
import { createUniqueId, createEffect } from "solid-js";
import { IconCircleAlert as CircleAlert, IconX as X, IconCheck as Check } from "./Icons.jsx";
import IconButton from "./IconButton.jsx";

// Ошибки открываются через showModal(), подтверждения — через show() без
// блокировки интерфейса. Оба уведомления используют нативный <dialog>.
export default function AppToast(options) {
  let dialogRef = null;
  const headingId = createUniqueId();
  const isError = () => Boolean(options.onDismiss);
  createEffect(
    () => [options.message, isError()],
    () => {
      const dialog = dialogRef;
      if (!options.message || !dialog) return undefined;
      if (dialog.open) dialog.close();
      if (isError()) dialog.showModal();
      else dialog.show();
      return () => {
        if (dialog.open) dialog.close();
      };
    },
  );
  return () => {
    if (!options.message) return null;

    // Неблокирующее подтверждение отображается внутри уже открытого диалога,
    // иначе браузерная top layer скрыла бы его за затемнением модального окна.
    const activeModal = () =>
      !isError()
        ? [...document.querySelectorAll("dialog.native-dialog[open]:not(.native-feedback-dialog)")].at(-1)
        : null;
    return (
      <Portal mount={activeModal() || document.body}>
        <dialog
          ref={dialogRef}
          class={[
            "modal",
            "native-dialog",
            "native-feedback-dialog",
            isError() ? "native-feedback-error" : "native-feedback-success",
          ].join(" ")}
          role={isError() ? "alertdialog" : "dialog"}
          aria-modal={isError() ? "true" : undefined}
          aria-labelledby={headingId}
          aria-live={isError() ? "assertive" : "polite"}
          onCancel={(event) => {
            event.preventDefault();
            options.onDismiss?.();
          }}
        >
          <div class="native-feedback-content">
            {isError() ? (
              <CircleAlert size={21} aria-hidden="true" />
            ) : (
              <Check size={20} aria-hidden="true" />
            )}
            <div class="native-feedback-copy">
              <h2 id={headingId}>{isError() ? "Ошибка" : "Готово"}</h2>
              <p class="toast-message">{options.message}</p>
            </div>
            {isError() && (
              <IconButton
                size="large"
                class="toast-close"
                aria-label="Закрыть уведомление об ошибке"
                onClick={options.onDismiss}
              >
                <X aria-hidden="true" />
              </IconButton>
            )}
          </div>
        </dialog>
      </Portal>
    );
  };
}
