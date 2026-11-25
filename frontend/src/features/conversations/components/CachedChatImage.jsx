import { createEffect } from "solid-js";

// Reserve the final geometry before loading. Unknown legacy dimensions use a
// stable frame too; object-fit preserves the original photo without cropping.
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
      // Reattached images already have their src and decoded content. The cold
      // path prepares nearby attachments without eagerly downloading the history.
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
