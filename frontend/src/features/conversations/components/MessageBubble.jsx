import { memo, useEffect, useRef, useState } from "react";
import Trash2 from "lucide-react/dist/esm/icons/trash-2.js";
import Check from "lucide-react/dist/esm/icons/check.js";
import CheckCheck from "lucide-react/dist/esm/icons/check-check.js";
import CircleAlert from "lucide-react/dist/esm/icons/circle-alert.js";
import CircleX from "lucide-react/dist/esm/icons/circle-x.js";
import Play from "lucide-react/dist/esm/icons/play.js";
import Pause from "lucide-react/dist/esm/icons/pause.js";

const API = import.meta.env.VITE_API_BASE_URL || "";

// Высоты декоративной звуковой волны общие для всех плееров — не создаём массив при каждом рендере.
const AUDIO_WAVE_BARS = [4, 7, 10, 6, 13, 8, 15, 10, 6, 12, 17, 9, 5, 13, 8, 16, 11, 6, 14, 9, 17, 7, 12, 5, 15, 9, 13, 6, 11, 16, 8, 12, 5, 14, 9, 7];
function formatLocalTime(value, options) {
  if (!value) return "";
  // SQLite timestamps without an explicit offset are stored as UTC.
  // The browser automatically applies the viewer's local time zone.
  const normalized = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(value) ? value : value + "Z";
  const date = new Date(normalized);
  return Number.isNaN(date.getTime()) ? "" : date.toLocaleString("ru-RU", options);
}

function formatAudioTime(value) {
  if (!Number.isFinite(value) || value < 0) return "0:00";
  const minutes = Math.floor(value / 60);
  const seconds = Math.floor(value % 60).toString().padStart(2, "0");
  return minutes + ":" + seconds;
}

function ChatAudioPlayer({ src, label }) {
  const audioRef = useRef(null);
  const [playing, setPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);

  useEffect(() => {
    setPlaying(false);
    setCurrentTime(0);
    setDuration(0);
  }, [src]);

  const togglePlayback = async () => {
    const audio = audioRef.current;
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

  const progress = duration > 0 ? Math.min(100, (currentTime / duration) * 100) : 0;

  return <div className={"chat-audio-player" + (playing ? " is-playing" : "")}>
    <audio
      ref={audioRef}
      className="chat-audio-native"
      src={src}
      preload="metadata"
      onLoadedMetadata={event => setDuration(Number.isFinite(event.currentTarget.duration) ? event.currentTarget.duration : 0)}
      onDurationChange={event => setDuration(Number.isFinite(event.currentTarget.duration) ? event.currentTarget.duration : 0)}
      onTimeUpdate={event => setCurrentTime(event.currentTarget.currentTime)}
      onPlay={() => setPlaying(true)}
      onPause={() => setPlaying(false)}
      onEnded={() => { setPlaying(false); setCurrentTime(0); }}
    />
    <button className="btn primary chat-audio-play" type="button" onClick={togglePlayback} aria-label={playing ? "Приостановить аудио" : "Воспроизвести аудио"}>
      {playing ? <Pause size={17} fill="currentColor" /> : <Play size={17} fill="currentColor" />}
    </button>
    <div className="chat-audio-track">
      <div className="chat-audio-wave" aria-hidden="true">
        {AUDIO_WAVE_BARS.map((height, index) => <span
          key={index}
          className={((index + 1) / AUDIO_WAVE_BARS.length * 100) <= progress ? "is-progress" : ""}
          style={{ height: height + "px", "--bar-index": index }}
        />)}
      </div>
      <input
        className="chat-audio-seek"
        type="range"
        min="0"
        max={duration || 0}
        step="0.1"
        value={Math.min(currentTime, duration || 0)}
        disabled={!duration}
        onChange={event => {
          const nextTime = Number(event.target.value);
          if (audioRef.current) {
            audioRef.current.currentTime = nextTime;
            setCurrentTime(nextTime);
          }
        }}
        aria-label={"Позиция аудио: " + label}
      />
      <div className="chat-audio-time"><span>{formatAudioTime(currentTime)}</span><span>{formatAudioTime(duration)}</span></div>
    </div>
  </div>;
}

function MessageBubble({ message, onDelete, viewerRole, personal = false }) {
  const [mediaUrl, setMediaUrl] = useState("");
  const bubbleRef = useRef(null);
  const media = message.metadata?.media;
  useEffect(() => {
    if (!media || media.archive_status !== "stored") return undefined;
    let objectUrl = "";
    let cancelled = false;
    const controller = new AbortController();
    const loadMedia = () => fetch(API + "/api/panel/messages/" + message.id + "/media", {
      credentials: "include",
      signal: controller.signal,
    }).then(response => {
      if (!response.ok) throw new Error("media unavailable");
      return response.blob();
    }).then(blob => {
      if (cancelled) return;
      objectUrl = URL.createObjectURL(blob);
      setMediaUrl(objectUrl);
    }).catch(() => {
      if (!cancelled) setMediaUrl("");
    });

    let observer;
    if ("IntersectionObserver" in window && bubbleRef.current) {
      observer = new IntersectionObserver(entries => {
        if (entries.some(entry => entry.isIntersecting)) {
          observer.disconnect();
          void loadMedia();
        }
      }, { rootMargin: "250px 0px" });
      observer.observe(bubbleRef.current);
    } else {
      void loadMedia();
    }
    return () => {
      cancelled = true;
      controller.abort();
      observer?.disconnect();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [message.id, media?.archive_status]);
  const sourceKind = media?.kind || message.content_type;
  const mimeType = (media?.mime_type || "").toLowerCase();
  // Telegram documents may actually contain playable audio/video or images.
  // Detect the browser presentation from MIME while preserving special types.
  const kind = sourceKind === "video_note"
    ? "video_note"
    : sourceKind === "animated_sticker"
      ? "animated_sticker"
      : mimeType.startsWith("image/")
        ? "photo"
        : mimeType.startsWith("video/")
          ? "video"
          : mimeType.startsWith("audio/")
            ? (sourceKind === "voice" ? "voice" : "audio")
            : sourceKind;
  const label = ({
    voice: "Голосовое сообщение",
    video_note: "Видеокружок",
    photo: mimeType === "image/gif" ? "GIF-анимация" : "Фотография",
    video: sourceKind === "video_sticker" ? "Видео-стикер" : sourceKind === "animation" ? "Анимация" : "Видео",
    audio: "Аудио",
    document: "Документ",
    sticker: "Стикер",
    animated_sticker: "Анимированный стикер",
    video_sticker: "Видео-стикер",
    animation: "Анимация"
  }[sourceKind] || "Вложение");
  return <div ref={bubbleRef} className={"message " + message.sender_role}>
    <div className="message-topline">
      {!(viewerRole === "teacher" && message.sender_role !== "admin") && <b>{message.sender}</b>}
      <div className="message-tools">
        <time className="message-time">{formatLocalTime(message.created_at, { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })}</time>
        {message.sender_role === viewerRole && viewerRole !== "admin" && (() => {
          const status = message.delivery_status || "unknown";
          const read = Boolean(message.panel_read_at);
          const title = read ? "Прочитано в UknowApp"
            : personal ? "Доставлено в UknowApp"
              : status === "pending" ? "Отправляется в Telegram"
                : status === "partial" ? "Частично доставлено в Telegram"
                  : status === "failed" ? "Не доставлено в Telegram"
                    : status === "blocked_contact" ? "Сообщение заблокировано: контактные данные не отправлены"
                      : status === "delivered" ? "Доставлено в Telegram"
                        : "Статус доставки не подтверждён";
          const statusClass = read ? " is-read"
            : ["failed", "blocked_contact"].includes(status) ? " is-failed"
              : ["partial", "unknown"].includes(status) ? " is-partial" : "";
          return <span className={"message-read-status" + statusClass} title={title} aria-label={title}>
            {status === "pending" ? <Check size={14}/>
              : ["failed", "blocked_contact"].includes(status) ? <CircleX size={15}/>
                : ["partial", "unknown"].includes(status) ? <CircleAlert size={15}/>
                  : <CheckCheck size={15}/>}
          </span>;
        })()}
        {message.can_delete && <button type="button" className="icon-btn danger-icon message-delete-btn" onClick={() => onDelete?.(message)} title="Удалить своё сообщение у всех" aria-label="Удалить своё сообщение"><Trash2 size={14}/></button>}
      </div>
    </div>
    {message.text && <p>{message.text}</p>}
    {mediaUrl && kind === "photo" && <img className="chat-media-image" src={mediaUrl} alt={label} />}
    {mediaUrl && ["voice", "audio"].includes(kind) && <ChatAudioPlayer src={mediaUrl} label={label} />}
    {mediaUrl && ["video", "video_note", "animation"].includes(kind) && <video className={"chat-media-video" + (kind === "video_note" ? " chat-media-video-note" : "")} controls playsInline preload="metadata" aria-label={label} src={mediaUrl} />}
    {mediaUrl && ["document", "photo"].includes(kind) && <a className="chat-media-download" href={mediaUrl} download={media?.file_name || label}>Скачать файл: {media?.file_name || label}</a>}
    {!mediaUrl && media && <small className="chat-media-status">{media.archive_status === "too_large_for_telegram_download" ? "Файл больше 20 МБ: Telegram не позволяет сохранить копию для веб-панели. Оригинал остаётся в исходном чате Telegram." : media.archive_status === "download_failed" ? "Не удалось сохранить копию вложения. Проверьте оригинал в Telegram." : "Загрузка вложения…"}</small>}
    {!media && !message.text && <p>Вложение: {message.content_type}</p>}
    {viewerRole === "admin" && (message.delivery_status && message.delivery_status !== "delivered" || message.metadata?.telegram_delivery_errors?.length > 0) && <div className="message-delivery">
      <div className="message-delivery-heading">{message.delivery_status === "pending"
        ? "Сообщение сохранено. Отправка в Telegram…"
        : message.delivery_status === "blocked_contact"
          ? "Сообщение заблокировано: контактные данные скрыты и не отправлены"
          : message.delivery_status === "partial"
          ? "В Telegram доставлено не всем адресатам"
          : "В Telegram не доставлено. Сообщение сохранено в UknowApp"}</div>
      {message.metadata?.telegram_delivery_errors?.length ? message.metadata.telegram_delivery_errors.map((error, index) => {
        const details = typeof error === "string"
          ? (() => { const separator = error.indexOf(":"); return separator < 0 ? { reason: error } : { name: error.slice(0, separator).trim(), reason: error.slice(separator + 1).trim() }; })()
          : error;
        return <div className="message-delivery-error" key={index}>
          {details.name && <span className={"message-delivery-name" + (details.role ? " " + details.role : "")}>{details.name}</span>}
          {details.name && <span className="message-delivery-dash"> — </span>}
          <span className="message-delivery-reason">{details.reason || "Причина не указана."}</span>
        </div>;
      }) : <div className="message-delivery-error"><span className="message-delivery-reason">Причина не указана.</span></div>}
    </div>}
  </div>;
}

export default memo(MessageBubble);
