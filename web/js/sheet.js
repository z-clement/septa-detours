// The mobile bottom sheet's heights (below 700 px the sidebar is a sheet
// over the map). Tapping its handle steps through them; some actions
// raise it.
//
// PURE: no DOM, no `maplibregl`. main.js sets the sheet's height from
// `sheetHeightPx` (a CSS variable), and uses the same number to keep the
// map's fit and pan clear of it: one source for both.

/** The sheet's heights, lowest first; also the tap order. */
export const SHEET_HEIGHTS = Object.freeze(["peek", "half", "full"]);

/** Where the sheet starts (decided: the list shows on first load). */
export const SHEET_START = "half";

/** Peek: the handle and the status line (about three lines on a phone). */
export const SHEET_PEEK_PX = 112;

/** Half and full, as fractions of the viewport's height. */
const SHEET_FRACTIONS = Object.freeze({ half: 0.5, full: 0.9 });

/**
 * The sheet's position in `SHEET_HEIGHTS`.
 *
 * @param {string} sheet
 * @returns {number}
 * @throws {RangeError} not a sheet height (a bug, not bad data)
 */
function sheetIndex(sheet) {
  const index = SHEET_HEIGHTS.indexOf(sheet);
  if (index === -1) {
    throw new RangeError(`not a sheet height: ${sheet}`);
  }
  return index;
}

/**
 * The height a tap on the handle moves to: peek -> half -> full -> peek.
 *
 * @param {string} sheet
 * @returns {string}
 */
export function nextSheet(sheet) {
  return SHEET_HEIGHTS[(sheetIndex(sheet) + 1) % SHEET_HEIGHTS.length];
}

/**
 * The sheet raised to at least `atLeast`; never lowered.
 *
 * @param {string} sheet
 * @param {string} atLeast
 * @returns {string}
 */
export function raisedSheet(sheet, atLeast) {
  return SHEET_HEIGHTS[Math.max(sheetIndex(sheet), sheetIndex(atLeast))];
}

/**
 * The sheet's height in CSS pixels for a viewport `viewportHeight` tall.
 *
 * Half and full are fractions, rounded to whole pixels. Peek is
 * `SHEET_PEEK_PX`, but never taller than half (a short landscape phone),
 * so the heights always rise in tap order.
 *
 * @param {string} sheet
 * @param {number} viewportHeight
 * @returns {number}
 */
export function sheetHeightPx(sheet, viewportHeight) {
  sheetIndex(sheet);
  const half = Math.round(viewportHeight * SHEET_FRACTIONS.half);
  if (sheet === "peek") {
    return Math.min(SHEET_PEEK_PX, half);
  }
  return sheet === "half" ? half : Math.round(viewportHeight * SHEET_FRACTIONS.full);
}
