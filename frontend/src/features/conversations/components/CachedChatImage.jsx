import { createEffect } from "solid-js";

// Резервируем место до загрузки; фото сохраняет пропорции.
function frameSize(width, height) {
  const w = Number(width);
  const h = Number(height);
  if (!(w > 0 && h > 0 && Number.isFinite(w) && Number.isFinite(h))) return [320, 240];
  const scale = Math.min(1, 420 / w, 420 / h);
  return [Math.max(1, Math.round(w * scale)), Math.max(1, Math.round(h * scale))];
}

export default function CachedChatImage(options) {
  let frame;
  const size = () => frameSize(options.width, options.height);
  createEffect(
    () => [options.cache, options.chatKey, options.messageId, options.src, options.alt, options.width, options.height],
    ([cache, chatKey, messageId, src, alt, width, height]) => {
      const lease = cache.acquireImage(chatKey, messageId, src, Number(width), Number(height));
      const image = lease.image;
      image.className = "chat-media-image";
      image.alt = alt;
      image.decoding = "async";
      image.loading = "eager";
      frame.appendChild(image);
      let observer;
      // Повторно используем загруженное изображение и не скачиваем всю историю заранее.
      if (!image.getAttribute("src")) {
        const load = () => { observer?.disconnect(); image.src = src; };
        if (typeof IntersectionObserver === "function") {
          observer = new IntersectionObserver(entries => {
            if (entries.some(entry => entry.isIntersecting)) load();
          }, { rootMargin: "600px" });
          observer.observe(frame);
        } else load();
      }
      return () => {
        observer?.disconnect();
        image.remove();
        cache.releaseImage(lease);
      };
    },
  );
  return <div ref={frame} class="chat-media-frame"
    style={{ width: size()[0] + "px", "aspect-ratio": size().join(" / ") }} />;
}
