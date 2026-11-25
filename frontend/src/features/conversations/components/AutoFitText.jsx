import { createEffect } from "solid-js";

// Batch reads and writes across all names. Opening a long conversation should
// trigger one layout per measurement phase rather than one per sender.
const pending = new Set();
const mounted = new Map();
let frame = 0;
let observer;

function schedule(items) {
  for (const item of items) pending.add(item);
  if (frame || !pending.size) return;
  frame = requestAnimationFrame(() => {
    frame = 0;
    const items = [...pending];
    pending.clear();
    const compact = window.matchMedia("(max-width: 760px)").matches;
    for (const item of items) {
      item.available = item.container.clientWidth;
      item.base = compact ? item.mobileSize : item.baseSize;
    }
    const visible = items.filter(item => item.available > 0);
    for (const item of visible) {
      item.content.style.transform = "none";
      item.content.style.fontSize = item.base + "px";
    }
    for (const item of visible) {
      const natural = item.content.scrollWidth || 1;
      item.size = Math.min(item.base, Math.max(item.minimum, item.base * (item.available - 1) / natural));
    }
    for (const item of visible) item.content.style.fontSize = item.size.toFixed(2) + "px";
    for (const item of visible) item.fitted = item.content.scrollWidth;
    for (const item of visible) {
      if (item.fitted > item.available) {
        const ratio = Math.max(0.01, (item.available - 1) / item.fitted);
        item.content.style.transform = `scaleX(${ratio})`;
      }
    }
  });
}

function onResize(entries) {
  schedule(entries.map(entry => mounted.get(entry.target)).filter(Boolean));
}
const fitAll = () => schedule(mounted.values());

export default function AutoFitText(options) {
  let container;
  let content;
  createEffect(
    () => [options.text, options.baseSize, options.mobileSize, options.minSize],
    ([, baseSize = 14, mobileSize = baseSize, minimum = 11]) => {
      const item = { container, content, baseSize, mobileSize, minimum };
      if (!mounted.size) {
        if (typeof ResizeObserver === "function") observer = new ResizeObserver(onResize);
        else window.addEventListener("resize", fitAll);
        document.fonts?.ready.then(fitAll);
      }
      mounted.set(container, item);
      observer?.observe(container);
      schedule([item]);
      return () => {
        observer?.unobserve(container);
        pending.delete(item);
        mounted.delete(container);
        if (!mounted.size) {
          observer?.disconnect();
          window.removeEventListener("resize", fitAll);
        }
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
