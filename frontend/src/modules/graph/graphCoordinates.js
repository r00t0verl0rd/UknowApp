const MIN_ZOOM = 0.35;
const MAX_ZOOM = 2.5;

export function createOuterCoordinateSystem(step = 12) {
  let bounds = { left: 0, top: 0, width: 0, height: 0 };
  let scaleX = 1;
  let scaleY = 1;

  return {
    update(element) {
      if (!element) return bounds;
      const rect = element.getBoundingClientRect();
      bounds = { left: rect.left, top: rect.top, width: rect.width, height: rect.height };
      scaleX = rect.width / (element.clientWidth || rect.width || 1);
      scaleY = rect.height / (element.clientHeight || rect.height || 1);
      return bounds;
    },
    getBounds() {
      return bounds;
    },
    toLocal(clientX, clientY) {
      return {
        x: (clientX - bounds.left) / scaleX,
        y: (clientY - bounds.top) / scaleY,
      };
    },
    deltaToLocal(deltaX, deltaY) {
      return { x: deltaX / scaleX, y: deltaY / scaleY };
    },
    toClient(x, y) {
      return {
        x: bounds.left + x * scaleX,
        y: bounds.top + y * scaleY,
      };
    },
    snap(value) {
      return Math.round(value / step) * step;
    },
    getStep() {
      return step;
    },
  };
}

export function createInnerGraphCoordinateSystem() {
  let zoom = 1;
  let panX = 0;
  let panY = 0;

  const clampZoom = value => Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, value));

  return {
    get zoom() {
      return zoom;
    },
    get pan() {
      return { x: panX, y: panY };
    },
    toGraphPoint(point) {
      return { x: (point.x - panX) / zoom, y: (point.y - panY) / zoom };
    },
    snapPoint(point, outer) {
      return {
        x: outer.snap(point.x * zoom) / zoom,
        y: outer.snap(point.y * zoom) / zoom,
      };
    },
    zoomAt(point, factor) {
      const nextZoom = clampZoom(zoom * factor);
      if (nextZoom === zoom) return false;
      const graphX = (point.x - panX) / zoom;
      const graphY = (point.y - panY) / zoom;
      zoom = nextZoom;
      panX = point.x - graphX * zoom;
      panY = point.y - graphY * zoom;
      return true;
    },
    panBy(x, y) {
      panX += x;
      panY += y;
    },
    transform() {
      return `translate3d(${panX}px, ${panY}px, 0) scale(${zoom})`;
    },
    reset() {
      zoom = 1;
      panX = 0;
      panY = 0;
    },
  };
}
