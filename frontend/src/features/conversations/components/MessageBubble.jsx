import { createSignal, createEffect, createUniqueId } from "solid-js";
import {
  IconTrash2 as Trash2,
  IconInfo as Info,
  IconX as X,
  IconCheck as Check,
  IconCheckCheck as CheckCheck,
  IconCircleX as CircleX,
  IconPlay as Play,
  IconPause as Pause,
} from "../../../shared/components/Icons.jsx";
import { formatMessageTime } from "../services/formatMessageTime.js";
import { getDeliveryDetails } from "../services/deliveryPresentation.js";
import IconButton from "../../../shared/components/IconButton.jsx";
import { messageMediaUrl } from "../services/conversationsApi.js";

// Высоты декоративной звуковой волны общие для всех плееров — не создаём массив при каждом рендере.
const AUDIO_WAVE_BARS = [
  4, 7, 10, 6, 13, 8, 15, 10, 6, 12, 17, 9, 5, 13, 8, 16, 11, 6, 14, 9, 17, 7, 12, 5, 15, 9, 13, 6, 11, 16, 8,
  12, 5, 14, 9, 7,
];
function formatAudioTime(value) {
  if (!Number.isFinite(value) || value < 0) return "0:00";
  const minutes = Math.floor(value / 60);
  const seconds = Math.floor(value % 60)
    .toString()
    .padStart(2, "0");
  return minutes + ":" + seconds;
}
function ChatAudioPlayer(options) {
  let audioRef = null;
  const [playing, setPlaying] = createSignal(false);
  const [currentTime, setCurrentTime] = createSignal(0);
  const [duration, setDuration] = createSignal(0);
  createEffect(
    () => [options.src],
    () => {
      setPlaying(false);
      setCurrentTime(0);
      setDuration(0);
    },
  );
  const togglePlayback = async () => {
    const audio = audioRef;
    if (!audio) return;
    if (audio.paused) {
      try {
        await audio.play();
      } catch {
        setPlaying(false);
      }
    } else {
      audio.pause();
    }
  };
  const progress = () => (duration() > 0 ? Math.min(100, (currentTime() / duration()) * 100) : 0);
  return (
    <div class={"chat-audio-player" + (playing() ? " is-playing" : "")}>
      <audio
        ref={audioRef}
        class="chat-audio-native"
        src={options.src}
        preload="none"
        onLoadedMetadata={(event) =>
          setDuration(Number.isFinite(event.currentTarget.duration) ? event.currentTarget.duration : 0)
        }
        onDurationChange={(event) =>
          setDuration(Number.isFinite(event.currentTarget.duration) ? event.currentTarget.duration : 0)
        }
        onTimeUpdate={(event) => setCurrentTime(event.currentTarget.currentTime)}
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onEnded={() => {
          setPlaying(false);
          setCurrentTime(0);
        }}
      />
      <button
        class="btn primary chat-audio-play"
        type="button"
        onClick={togglePlayback}
        aria-label={playing() ? "Приостановить аудио" : "Воспроизвести аудио"}
      >
        {playing() ? <Pause size={17} fill="currentColor" /> : <Play size={17} fill="currentColor" />}
      </button>
      <div class="chat-audio-track">
        <div class="chat-audio-wave" aria-hidden="true">
          {AUDIO_WAVE_BARS.map((height, index) => (
            <span
              class={((index + 1) / AUDIO_WAVE_BARS.length) * 100 <= progress() ? "is-progress" : ""}
              style={{
                height: height + "px",
                "--bar-index": index,
              }}
            />
          ))}
        </div>
        <input
          class="chat-audio-seek"
          type="range"
          min="0"
          max={duration() || 0}
          step="0.1"
          value={Math.min(currentTime(), duration() || 0)}
          disabled={!duration()}
          onInput={(event) => {
            const nextTime = Number(event.target.value);
            if (audioRef) {
              audioRef.currentTime = nextTime;
              setCurrentTime(nextTime);
            }
          }}
          aria-label={"Позиция аудио: " + options.label}
        />
        <div class="chat-audio-time">
          <span>{formatAudioTime(currentTime())}</span>
          <span>{formatAudioTime(duration())}</span>
        </div>
      </div>
    </div>
  );
}
function MessageBubble(options) {
  const deliveryPopoverId = createUniqueId();
  const media = () => options.message.metadata?.media;
  const mediaUrl = () => media()?.archive_status === "stored"
    ? messageMediaUrl(options.message.id, options.personalChat) : "";
  const sourceKind = () => media()?.kind || options.message.content_type;
  const mimeType = () => (media()?.mime_type || "").toLowerCase();
  // Документы Telegram могут содержать воспроизводимое медиа.
  const kind = () =>
    sourceKind() === "video_note"
      ? "video_note"
      : sourceKind() === "animated_sticker"
        ? "animated_sticker"
        : mimeType().startsWith("image/")
          ? "photo"
          : mimeType().startsWith("video/")
            ? "video"
            : mimeType().startsWith("audio/")
              ? sourceKind() === "voice"
                ? "voice"
                : "audio"
              : sourceKind();
  const label = () =>
    ({
      voice: "Голосовое сообщение",
      video_note: "Видеокружок",
      photo: mimeType() === "image/gif" ? "GIF-анимация" : "Фотография",
      video:
        sourceKind() === "video_sticker"
          ? "Видео-стикер"
          : sourceKind() === "animation"
            ? "Анимация"
            : "Видео",
      audio: "Аудио",
      document: "Документ",
      sticker: "Стикер",
      animated_sticker: "Анимированный стикер",
      video_sticker: "Видео-стикер",
      animation: "Анимация",
    })[sourceKind()] || "Вложение";
  const deliveryDetails = () => getDeliveryDetails(options.message.metadata, true, options.deliveryRecipients || []);
  return (
    <div class={"message " + options.message.sender_role} data-view-anchor={"message:" + options.message.id}>
      <div class="message-content">
        <div class="message-topline">
          <b data-chat-name-role={options.message.sender_role}>{options.message.sender}</b>
          <div class="message-tools">
            <time class="message-time">{formatMessageTime(options.message.created_at, options.nowMs)}</time>
            {options.message.sender_role === options.viewerRole &&
              (options.viewerRole !== "admin" || options.personalChat) &&
              (() => {
                const status = options.message.delivery_status || "unknown";
                const read = Boolean(options.message.panel_read_at);
                const pending = status === "pending";
                const blocked = status === "blocked_contact";
                const title = read
                  ? "Прочитано в UknowApp"
                  : blocked
                    ? "Сообщение заблокировано системой"
                    : pending
                      ? "Отправлено из UknowApp"
                      : "Доставлено в UknowApp";
                const statusClass = read ? " is-read" : blocked ? " is-failed" : "";
                return (
                  <span class={"message-read-status" + statusClass} title={title} aria-label={title}>
                    {blocked ? <CircleX size={15} /> : pending ? <Check size={14} /> : <CheckCheck size={15} />}
                  </span>
                );
              })()}
          </div>
        </div>
        {options.message.text && <p>{options.message.text}</p>}
        {mediaUrl() && kind() === "photo" && <img loading="lazy" decoding="async" class="chat-media-image" src={mediaUrl()} alt={label()} />}
        {mediaUrl() && ["voice", "audio"].includes(kind()) && (
          <ChatAudioPlayer src={mediaUrl()} label={label()} />
        )}
        {mediaUrl() && ["video", "video_note", "animation"].includes(kind()) && (
          <video
            class={"chat-media-video" + (kind() === "video_note" ? " chat-media-video-note" : "")}
            controls
            playsInline
            preload="none"
            aria-label={label()}
            src={mediaUrl()}
          />
        )}
        {mediaUrl() && ["document", "photo"].includes(kind()) && (
          <a class="chat-media-download" href={mediaUrl()} download={media()?.file_name || label()}>
            Скачать файл: {media()?.file_name || label()}
          </a>
        )}
        {!mediaUrl() &&
          ["too_large_for_telegram_download", "download_failed"].includes(media()?.archive_status) && (
            <small class="chat-media-status">
              {media().archive_status === "too_large_for_telegram_download"
                ? "Файл больше 20 МБ: Telegram не позволяет сохранить копию для веб-панели. Оригинал остаётся в исходном чате Telegram."
                : "Не удалось сохранить копию вложения. Проверьте оригинал в Telegram."}
            </small>
          )}
        {!media() && !options.message.text && <p>Вложение: {options.message.content_type}</p>}
      </div>
      {(options.message.can_delete || (options.viewerRole === "admin" && deliveryDetails().length > 0)) && (
        <div class="message-actions">
          {options.viewerRole === "admin" && deliveryDetails().length > 0 && (
            <IconButton
              type="button"
              size="compact"
              class="message-detail-btn"
              data-delivery-complete={deliveryDetails().every(detail => detail.delivered) ? "true" : "false"}
              popovertarget={deliveryPopoverId}
              aria-controls={deliveryPopoverId}
              aria-haspopup="dialog"
              title="Подробности внешней доставки"
              aria-label="Подробности внешней доставки"
            >
              <Info aria-hidden="true" />
            </IconButton>
          )}
          {options.message.can_delete && (
            <IconButton
              type="button"
              size="compact"
              class="message-delete-btn"
              onClick={() => options.onDelete?.(options.message)}
              title="Удалить своё сообщение у всех"
              aria-label="Удалить своё сообщение"
            >
              <Trash2 aria-hidden="true" />
            </IconButton>
          )}
        </div>
      )}
      {options.viewerRole === "admin" && deliveryDetails().length > 0 && (
        <section
          id={deliveryPopoverId}
          popover="auto"
          class="message-delivery-popover"
          role="dialog"
          aria-label="Подробности внешней доставки"
        >
          <div class="message-delivery-popover-heading">
            <h3><Check size={19} aria-hidden="true" /> Сообщение доставлено в UknowApp</h3>
            <button
              type="button"
              class="message-delivery-popover-close"
              popovertarget={deliveryPopoverId}
              popovertargetaction="hide"
              aria-label="Закрыть подробности доставки"
            >
              <X size={16} aria-hidden="true" />
            </button>
          </div>
          <p class="message-delivery-subtitle">Доставка через мессенджеры</p>
          <ul>
            {deliveryDetails().map((detail) => (
              <li class={detail.delivered ? "is-delivered" : ""}>
                <strong>{detail.namedRecipient ? <>{detail.channel} · <b data-chat-name-role={detail.role}>{detail.namedRecipient}</b></> : detail.title}</strong>
                <span>{detail.description}</span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
export default MessageBubble;
