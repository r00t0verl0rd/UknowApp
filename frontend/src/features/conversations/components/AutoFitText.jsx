import { createEffect } from "solid-js";

// Keep names on a single line at their regular font size whenever possible.
// Resize only when needed; use gentle horizontal compression as the last
// resort rather than an unreadably tiny font or a clipped surname.
export default function AutoFitText(options) {
  let container;
  let content;

  const fit = () => {
    if (!container || !content) return;
    const available = container.clientWidth;
    if (available <= 0) return;

    const compact = window.matchMedia("(max-width: 760px)").matches;
    const base = compact ? (options.mobileSize ?? options.baseSize ?? 14) : (options.baseSize ?? 14);
    const minimum = options.minSize ?? 11;
    content.style.transform = "none";
    content.style.fontSize = base + "px";
    const natural = content.scrollWidth;
    if (!natural) return;

    const size = Math.min(base, Math.max(minimum, base * (available - 1) / natural));
    content.style.fontSize = size.toFixed(2) + "px";
    const fitted = content.scrollWidth;
    const ratio = fitted > available ? Math.max(0.01, (available - 1) / fitted) : 1;
    content.style.transform = ratio < 1 ? `scaleX(${ratio})` : "none";
  };

  createEffect(
    () => [options.text, options.baseSize, options.mobileSize, options.minSize],
    () => {
      fit();
      const onResize = () => fit();
      const observer = typeof ResizeObserver === "function"
        ? new ResizeObserver(onResize) : null;
      if (observer) observer.observe(container);
      else window.addEventListener("resize", onResize);
      document.fonts?.ready.then(() => {
        if (container?.isConnected) fit();
      });
      return () => {
        observer?.disconnect();
        window.removeEventListener("resize", onResize);
      };
    },
  );

  return (
    <span class={"chat-name-fit" + (options.class ? " " + options.class : "")}
      ref={container} title={options.text} aria-label={options.text}>
      <span class="chat-name-fit-content" ref={content}>{options.children}</span>
    </span>
  );
}
