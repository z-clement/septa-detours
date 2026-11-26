// Detour logic: whether a detour is in effect.
//
// PURE: no DOM, no `maplibregl`, no fetch, so `node --test` can run it.

/**
 * Whether a detour is in effect at `now`, by its overall start and end.
 *
 * The page's one timing rule (since contract 6 no file carries a timing):
 * "active" from `start` to `end` inclusive, "upcoming" before,
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


/**
 * Whether the map draws a detour now: `detourTiming` "active", or
 * "unknown" (shown rather than hidden: a detour with odd dates may well
 * be running). Upcoming and ended detours stay in the route panel.
 *
 * @param {string | null | undefined} start
 * @param {string | null | undefined} end
 * @param {Date} now
 * @returns {boolean}
 */
export function isInEffect(start, end, now) {
  const timing = detourTiming(start, end, now);
  return timing === "active" || timing === "unknown";
}

/**
 * The `source_key`s of the detour features in effect at `now`, for the
 * map's filters (starts, skipped, paths: each feature carries its
 * detour's `start` and `end`).
 *
 * @param {object[]} features GeoJSON features (properties `source_key`,
 *   `start`, `end`)
 * @param {Date} now
 * @returns {Set<string>}
 */
export function inEffectKeys(features, now) {
  const keys = new Set();
  for (const { properties } of features) {
    if (isInEffect(properties.start, properties.end, now)) {
      keys.add(properties.source_key);
    }
  }
  return keys;
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

/**
 * The focused route's rejoin points, for the map: where each detour in
 * effect gets back on its route.
 *
 * In effect = `isInEffect`, the same rule as the map's other layers.
 * Detours without a `rejoin_point` are left out. Feature properties:
 * `key` (the route), `source_key` (the detour: the map's feature id, as
 * for start dots), `color` (the route's, or null).
 *
 * @param {object} detail a route detail file (`key`, `detours`)
 * @param {string | null} color the route's color (routes.json)
 * @param {Date} now
 * @returns {{type: "FeatureCollection", features: object[]}}
 */
export function rejoinCollection(detail, color, now) {
  const features = [];
  for (const detour of detail.detours) {
    const point = detour.rejoin_point;
    if (point === null || !isInEffect(detour.start, detour.end, now)) {
      continue;
    }
    features.push({
      type: "Feature",
      geometry: { type: "Point", coordinates: [point.lon, point.lat] },
      properties: { key: detail.key, source_key: detour.source_key, color },
    });
  }
  return { type: "FeatureCollection", features };
}

/**
 * The box around some detours' drawn geometry: start and rejoin points,
 * skipped stretches, paths. For the camera (UI plan C1): a focused
 * route's detours in effect, or one selected detour.
 *
 * @param {object[]} detours detour objects (route detail)
 * @returns {[[number, number], [number, number]] | null}
 *   `[[west, south], [east, north]]` as fitBounds takes; null when none
 *   has any geometry (unplaced detours only, or none)
 */
export function detourBounds(detours) {
  let west = Infinity;
  let south = Infinity;
  let east = -Infinity;
  let north = -Infinity;
  const add = ([lon, lat]) => {
    west = Math.min(west, lon);
    south = Math.min(south, lat);
    east = Math.max(east, lon);
    north = Math.max(north, lat);
  };
  for (const detour of detours) {
    for (const point of [detour.start_point, detour.rejoin_point]) {
      if (point != null) {
        add([point.lon, point.lat]);
      }
    }
    for (const line of [detour.skipped, detour.path]) {
      for (const position of line ?? []) {
        add(position);
      }
    }
  }
  return west === Infinity ? null : [
    [west, south],
    [east, north],
  ];
}
