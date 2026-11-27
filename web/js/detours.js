// Detour logic: whether a detour is in effect.
//
// PURE: no DOM, no `maplibregl`, no fetch, so `node --test` can run it.

import { SEPTA_TIME_ZONE } from "./format.js";

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


const WEEKDAY_INDEX = Object.freeze({ Mon: 0, Tue: 1, Wed: 2, Thu: 3, Fri: 4, Sat: 5, Sun: 6 });

let localClockFormat = null;

/** The formatter behind `localClock`, made on first use (so a test's TZ
 * change, made after imports, applies to it as it would to a page's). */
function clockFormat() {
  localClockFormat ??= new Intl.DateTimeFormat("en-US", {
    timeZone: SEPTA_TIME_ZONE,
    weekday: "short",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  });
  return localClockFormat;
}

/**
 * The weekday and time of day at `now` in SEPTA's time zone, whatever the
 * browser's own zone (daily hours are local times).
 *
 * @param {Date} now
 * @returns {{day: number, minutes: number}} `day`: Monday = 0;
 *   `minutes`: since local midnight
 */
export function localClock(now) {
  const parts = Object.fromEntries(
    clockFormat()
      .formatToParts(now)
      .map(({ type, value }) => [type, value]),
  );
  return {
    day: WEEKDAY_INDEX[parts.weekday],
    minutes: Number(parts.hour) * 60 + Number(parts.minute),
  };
}

/** "07:30" -> 450. */
function minutesOf(hhmm) {
  const [hours, minutes] = hhmm.split(":").map(Number);
  return hours * 60 + minutes;
}

/**
 * Whether `now` is inside a detour's daily hours (contract `hours`).
 *
 * From `start` (inclusive) to `end` (exclusive), on its `days`. An `end`
 * before `start` is overnight: the evening part counts on its `days`, the
 * morning part on the day after each.
 *
 * @param {{days: number[], start: string, end: string} | null} hours
 *   null: all day (true)
 * @param {Date} now
 * @returns {boolean}
 */
export function inHours(hours, now) {
  if (hours === null) {
    return true;
  }
  const { day, minutes } = localClock(now);
  const start = minutesOf(hours.start);
  const end = minutesOf(hours.end);
  if (start < end) {
    return hours.days.includes(day) && minutes >= start && minutes < end;
  }
  const yesterday = (day + 6) % 7;
  return (
    (hours.days.includes(day) && minutes >= start) ||
    (hours.days.includes(yesterday) && minutes < end)
  );
}

/**
 * A detour feature's daily hours, from its flat `hours_*` properties
 * (contract 8), in the detour object's shape; null without hours.
 *
 * @param {object} properties
 * @returns {{days: number[], start: string, end: string} | null}
 */
export function hoursOf(properties) {
  if (properties.hours_days == null) {
    return null;
  }
  return {
    days: [...properties.hours_days].map(Number),
    start: properties.hours_start,
    end: properties.hours_end,
  };
}

/**
 * Whether the map draws a detour now: `detourTiming` "active", or
 * "unknown" (shown rather than hidden: a detour with odd dates may well
 * be running), and inside its daily hours if it has any (U8: outside
 * them it's hidden like an upcoming one). Upcoming, ended and off-hours
 * detours stay in the route panel.
 *
 * @param {string | null | undefined} start
 * @param {string | null | undefined} end
 * @param {Date} now
 * @param {{days: number[], start: string, end: string} | null} [hours]
 * @returns {boolean}
 */
export function isInEffect(start, end, now, hours = null) {
  const state = detourState(start, end, hours, now);
  return state === "active" || state === "unknown";
}

/**
 * A detour's state at `now` for the page's lists and groups:
 * `detourTiming`'s, except that a detour within its dates (active, or
 * unknown) but outside its daily hours is "resting": not running now
 * (render sweep finding 7: the map hides it, so "In effect" shouldn't
 * list it).
 *
 * @param {string | null | undefined} start
 * @param {string | null | undefined} end
 * @param {{days: number[], start: string, end: string} | null | undefined} hours
 *   null or missing: all day
 * @param {Date} now
 * @returns {"active" | "resting" | "upcoming" | "ended" | "unknown"}
 */
export function detourState(start, end, hours, now) {
  const timing = detourTiming(start, end, now);
  if ((timing === "active" || timing === "unknown") && !inHours(hours ?? null, now)) {
    return "resting";
  }
  return timing;
}

/**
 * The `source_key`s of the detour features in effect at `now`, for the
 * map's filters (starts, skipped, paths: each feature carries its
 * detour's `start`, `end` and `hours_*`).
 *
 * @param {object[]} features GeoJSON features (properties `source_key`,
 *   `start`, `end`)
 * @param {Date} now
 * @returns {Set<string>}
 */
export function inEffectKeys(features, now) {
  const keys = new Set();
  for (const { properties } of features) {
    if (isInEffect(properties.start, properties.end, now, hoursOf(properties))) {
      keys.add(properties.source_key);
    }
  }
  return keys;
}

/** The route panel's group order: in effect first, ended last (D6). */
export const TIMING_ORDER = Object.freeze(["active", "resting", "upcoming", "unknown", "ended"]);

/**
 * A route's detours grouped by `detourState`, for the route panel.
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
    groups.get(detourState(detour.start, detour.end, detour.hours, now)).push(detour);
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
    if (point === null || !isInEffect(detour.start, detour.end, now, detour.hours)) {
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
