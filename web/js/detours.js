// Detour logic: whether a detour is in effect.
//
// PURE: no DOM, no `maplibregl`, no fetch, so `node --test` can run it.

/**
 * Whether a detour is in effect at `now`, by its overall start and end.
 *
 * The same rule as Python's `export.site.detour_timing` (keep them in
 * step): "active" from `start` to `end` inclusive, "upcoming" before,
 * "ended" after. "unknown" when a time is missing (`null` from plain JSON,
 * `undefined` from a clicked feature), when `end` is before `start` (bad
 * data: "upcoming" and "ended" could both be wrong), or, unlike Python,
 * when a time doesn't parse. Recurring windows ("7am - 4pm Mon thru Fri")
 * aren't parsed, so "active" means "inside the overall dates", not
 * "running right now".
 *
 * Takes the two times, not a detour, so it serves both `routes.json`
 * windows (`detourTiming(w[0], w[1], now)`) and detour objects
 * (`detourTiming(d.start, d.end, now)`).
 *
 * @param {string | null | undefined} start ISO 8601 with an offset
 * @param {string | null | undefined} end ISO 8601 with an offset
 * @param {Date} now
 * @returns {"active" | "upcoming" | "ended" | "unknown"}
 * @throws {TypeError} `now` isn't a valid Date (a bug, not bad data)
 */
export function detourTiming(start, end, now) {
  if (!(now instanceof Date) || Number.isNaN(now.getTime())) {
    throw new TypeError(`now must be a valid Date, got ${now}`);
  }
  // Date.parse gives NaN for null, undefined and unparseable text alike.
  // (Not `new Date(null)`: that's Jan 1, 1970, a real-looking time.)
  const startMs = Date.parse(start);
  const endMs = Date.parse(end);
  if (Number.isNaN(startMs) || Number.isNaN(endMs) || endMs < startMs) {
    return "unknown";
  }
  const nowMs = now.getTime();
  if (nowMs < startMs) {
    return "upcoming";
  }
  if (nowMs > endMs) {
    return "ended";
  }
  return "active";
}


/** The route panel's group order: in effect first, ended last (D6). */
export const TIMING_ORDER = Object.freeze(["active", "upcoming", "unknown", "ended"]);

/**
 * A route's detours grouped by `detourTiming`, for the route panel.
 *
 * Groups come in `TIMING_ORDER`; a group with no detours is left out.
 * Within a group, detours keep the order given (snapshot order).
 *
 * @param {object[]} detours detour objects (a route detail's `detours`)
 * @param {Date} now
 * @returns {{timing: string, detours: object[]}[]}
 */
export function groupByTiming(detours, now) {
  const groups = new Map(TIMING_ORDER.map((timing) => [timing, []]));
  for (const detour of detours) {
    groups.get(detourTiming(detour.start, detour.end, now)).push(detour);
  }
  return TIMING_ORDER.filter((timing) => groups.get(timing).length > 0).map((timing) => ({
    timing,
    detours: groups.get(timing),
  }));
}
