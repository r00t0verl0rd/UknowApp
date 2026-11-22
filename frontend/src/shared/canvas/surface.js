// The host component sets the canvas CSS dimensions and disposes the surface on unmount.
export function createCanvasSurface(canvas, draw) {
  const context = canvas.getContext("2d");
  if (!context) throw new Error("Canvas 2D недоступен");
  let frame = 0;
  let disposed = false;
  let resolution;

  function invalidate() {
    if (disposed || frame) return;
    frame = requestAnimationFrame(() => {
      frame = 0;
      const { width, height } = canvas.getBoundingClientRect();
      if (!width || !height) return;
      const ratio = window.devicePixelRatio || 1;
      const pixelsX = Math.max(1, Math.round(width * ratio));
      const pixelsY = Math.max(1, Math.round(height * ratio));
      if (canvas.width !== pixelsX) canvas.width = pixelsX;
      if (canvas.height !== pixelsY) canvas.height = pixelsY;
      context.save();
      try {
        context.setTransform(pixelsX / width, 0, 0, pixelsY / height, 0, 0);
        context.clearRect(0, 0, width, height);
        draw(context, { width, height, ratio });
      } finally {
        context.restore();
      }
    });
  }

  function watchResolution() {
    resolution?.removeEventListener("change", watchResolution);
    resolution = window.matchMedia("(resolution: " + (window.devicePixelRatio || 1) + "dppx)");
    resolution.addEventListener("change", watchResolution);
    invalidate();
  }

  const observer = new ResizeObserver(invalidate);
  observer.observe(canvas);
  watchResolution();
  return {
    invalidate,
    dispose() {
      disposed = true;
      observer.disconnect();
      resolution.removeEventListener("change", watchResolution);
      cancelAnimationFrame(frame);
    },
  };
}
