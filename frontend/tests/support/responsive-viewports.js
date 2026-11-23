// Representative CSS viewport widths for visual regression checks.
// These are TEST SAMPLES, not CSS breakpoints or device hardware resolutions.
// 1024/1025 probe both sides of the current desktop switch.
export const RESPONSIVE_VIEWPORT_WIDTHS = Object.freeze([
  280, 320, 360, 390, 480, 640, 768, 1024, 1025, 1280, 1440, 1920,
]);
export const RESPONSIVE_MOBILE_WIDTHS = Object.freeze(
  RESPONSIVE_VIEWPORT_WIDTHS.filter(width => width <= 1024),
);
