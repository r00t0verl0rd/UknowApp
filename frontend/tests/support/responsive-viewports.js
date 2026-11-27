// Ширины окон для визуальных проверок, включая обе стороны границы 1024px.
export const RESPONSIVE_VIEWPORT_WIDTHS = Object.freeze([
  280, 320, 360, 390, 480, 640, 768, 1024, 1025, 1280, 1440, 1920,
]);
export const RESPONSIVE_MOBILE_WIDTHS = Object.freeze(
  RESPONSIVE_VIEWPORT_WIDTHS.filter(width => width <= 1024),
);
