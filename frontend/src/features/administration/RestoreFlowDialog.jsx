import { Show } from "solid-js";
import Modal from "../../shared/components/Modal.jsx";
import Button from "../../shared/components/Button.jsx";

export default function RestoreFlowDialog(options) {
  const phase = () => options.flow.phase;
  const working = () => phase() === "uploading" || phase() === "waiting";
  const title = () => ({
    uploading: "Загружаем и проверяем архив",
    waiting: "Восстанавливаем данные",
    delayed: "Проверка занимает больше времени",
    reauth: "Требуется повторный вход",
    completed: "Восстановление завершено",
    failed: "Не удалось восстановить копию",
  })[phase()] || "";
  const description = () => {
    switch (phase()) {
      case "uploading":
        return "Загружаем архив и проверяем его целостность. Пока сервер не примет копию, данные не заменяются.";
      case "waiting":
        return options.flow.current?.automaticRestart === false
          ? "Архив принят. Для применения копии требуется вручную перезапустить сервер. После запуска мы проверим результат."
          : "Архив принят. Сервер применяет копию и может ненадолго пропасть из сети при перезапуске. Это ожидаемо.";
      case "reauth":
        return "После замены базы прежняя сессия больше не действует. Чтобы проверить итог восстановления, завершите её и войдите заново. Переход произойдёт только после вашего подтверждения.";
      case "delayed":
        return "Сервер пока не подтвердил результат. Это не означает, что восстановление завершилось или закончилось ошибкой. Проверьте доступность сервера и повторите проверку.";
      case "completed":
        return "Сервер подтвердил, что данные из резервной копии успешно восстановлены.";
      case "failed":
        return "Сервер сообщил об ошибке восстановления. Проверьте исходные данные перед повторной попыткой.";
      default:
        return "";
    }
  };
  return (
    <Show when={phase() && phase() !== "login"}>
      <Modal
        class="restore-flow-dialog"
        role="alertdialog"
        labelledBy="restore-flow-title"
        describedBy="restore-flow-description"
        closeOnBackdrop={false}
        onClose={() => {}}
      >
        <div class="restore-flow-heading">
          <span class="restore-flow-eyebrow">РЕЗЕРВНОЕ КОПИРОВАНИЕ</span>
          <h2 id="restore-flow-title">{title()}</h2>
          <p id="restore-flow-description">{description()}</p>
        </div>

        <Show when={working()}>
          <div
            class="restore-flow-progress"
            role="progressbar"
            aria-label="Ход восстановления резервной копии"
            aria-valuetext={phase() === "uploading" ? "Загрузка и проверка архива" : "Ожидание восстановления и перезапуска"}
          >
            <span class="restore-flow-progress-bar" />
          </div>
          <p class="restore-flow-progress-note" role="status">
            {phase() === "uploading" ? "Загрузка и проверка архива…" : "Ожидаем подтверждение от сервера…"}
          </p>
        </Show>

        <ol class="restore-flow-steps">
          <li class={phase() !== "uploading" ? "is-complete" : "is-current"}>
            <span aria-hidden="true">{phase() === "uploading" ? "1" : "✓"}</span>
            {phase() === "uploading" ? "Загрузка и проверка архива" : "Архив проверен и принят"}
          </li>
          <li class={phase() === "uploading" ? "" : phase() === "completed" ? "is-complete" : phase() === "failed" ? "is-error" : "is-current"}>
            <span aria-hidden="true">{phase() === "completed" ? "✓" : phase() === "failed" ? "!" : "2"}</span>
            Восстановление и перезапуск
          </li>
          <li class={phase() === "completed" ? "is-complete" : phase() === "failed" ? "is-error" : phase() === "reauth" ? "is-current" : ""}>
            <span aria-hidden="true">{phase() === "completed" ? "✓" : phase() === "failed" ? "!" : "3"}</span>
            Проверка результата
          </li>
        </ol>

        <Show when={phase() === "reauth"}>
          <div class="restore-flow-actions">
            <Button variant="primary" onClick={options.flow.confirmRelogin}>
              Завершить сеанс и войти снова
            </Button>
          </div>
        </Show>
        <Show when={phase() === "delayed"}>
          <div class="restore-flow-actions">
            <Button variant="primary" onClick={options.flow.retry}>Проверить ещё раз</Button>
          </div>
        </Show>
        <Show when={phase() === "completed" || phase() === "failed"}>
          <div class="restore-flow-actions">
            <Button variant="primary" onClick={options.flow.dismiss}>Понятно</Button>
          </div>
        </Show>
      </Modal>
    </Show>
  );
}
