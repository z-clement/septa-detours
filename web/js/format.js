// Text for the page: times, labels, plurals.
//
// PURE: no DOM, no `maplibregl`, no fetch. That keeps it runnable under
// `node --test web/test/` (see web/test/format.test.js).

/** Detour times are SEPTA local time; show them that way on any machine. */
export const SEPTA_TIME_ZONE = "America/New_York";

/**
 * "1 route", "2 routes", "0 routes".
 *
 * @param {number} count
 * @param {string} singular e.g. "route"
 * @param {string} [pluralForm] defaults to `singular + "s"`; pass it for
 *   irregular words
 * @returns {string}
 */
export function plural(count, singular, pluralForm = `${singular}s`) {
  return `${count} ${count === 1 ? singular : pluralForm}`;
}

/**
 * Format an ISO 8601 time from the data as SEPTA local time.
 *
 * `new Date(iso)` reads the offset in the string, so the instant is exact;
 * `timeZone` then shows it in Philadelphia time whatever the viewer's
 * machine is set to. A missing value is shown as "(unknown)": `null` from
 * plain JSON (`new Date(null)` would quietly be Jan 1, 1970) or
 * `undefined` (a clicked feature: MapLibre drops null properties).
 *
 * @param {string | null | undefined} iso e.g. "2026-11-25T15:00:00-05:00"
 * @returns {string} e.g. "Nov 25, 2026, 3:00 PM"
 */
export function formatTime(iso) {
  if (iso === undefined || iso === null) {
    return "(unknown)";
  }
  return new Date(iso).toLocaleString("en-US", {
    timeZone: SEPTA_TIME_ZONE,
    dateStyle: "medium",
    timeStyle: "short",
  });
}

// --- The data contract's text (status.json, routes.json, detour objects) ---

/** Sidebar headings for routes.json's `mode` values. */
const MODE_LABELS = {
  metro: "Metro",
  trolley: "Trolleys",
  trackless: "Trackless Trolleys",
  bus: "Buses",
  rail: "Regional Rail",
};

/**
 * The sidebar heading for a mode: "Buses", "Regional Rail".
 *
 * A mode this page doesn't know (a newer export) shows as itself rather
 * than breaking the list; Python refuses unknown GTFS route types anyway.
 *
 * @param {string} mode a routes.json `mode`
 * @returns {string}
 */
export function modeLabel(mode) {
  return Object.hasOwn(MODE_LABELS, mode) ? MODE_LABELS[mode] : mode;
}

/**
 * "Route 21 Chestnut-Walnut", or "Route K" when there's no long name.
 *
 * @param {object} route a routes.json entry
 * @returns {string}
 */
export function routeLabel(route) {
  return route.long_name === null
    ? `Route ${route.short_name}`
    : `Route ${route.short_name} ${route.long_name}`;
}

/**
 * The status line: when the detours are from and how many are drawn.
 *
 * e.g. "Detours as of Nov 25, 2026, 7:11 AM: 166 total, 134 on the map,
 * 27 without a location, 5 not matched to a route". The last two parts are
 * left out when zero. A hand-named snapshot has no fetch time, so its file
 * name is shown instead.
 *
 * @param {object} status status.json
 * @returns {string}
 */
export function statusLine(status) {
  const { total, matched, placed } = status.detours;
  const when =
    status.snapshot_fetched_at === null
      ? `in ${status.snapshot}`
      : `as of ${formatTime(status.snapshot_fetched_at)}`;
  if (total === 0) {
    return `No detours ${when}`;
  }
  const parts = [`${total} total`, `${placed} on the map`];
  if (matched > placed) {
    parts.push(`${matched - placed} without a location`);
  }
  if (total > matched) {
    parts.push(`${total - matched} not matched to a route`);
  }
  return `Detours ${when}: ${parts.join(", ")}`;
}

/** The sidebar's word for each `detourTiming` result. */
export const TIMING_WORDS = Object.freeze({
  active: "now",
  upcoming: "later",
  ended: "ended",
  unknown: "unknown",
});

/** The alerts API's route id prefixes; what follows is the route's name. */
const API_ROUTE_PREFIXES = ["bus_route_", "trolley_route_", "rr_route_"];

/**
 * A display name for an alerts API route id: "bus_route_L" -> "L".
 *
 * Upper-cased after the prefix, so "rr_route_mfo" -> "MFO". An id without
 * a known prefix is shown unchanged rather than guessed at.
 *
 * @param {string} apiRouteId e.g. a `status.unmatched` detour's `route`
 * @returns {string}
 */
export function apiRouteName(apiRouteId) {
  const prefix = API_ROUTE_PREFIXES.find((p) => apiRouteId.startsWith(p));
  return prefix === undefined ? apiRouteId : apiRouteId.slice(prefix.length).toUpperCase();
}

/**
 * Where a detour runs: "17th & Washington to 17th & Mifflin".
 *
 * The same place at both ends (a stop closure: "Market & Schuylkill Ave"
 * twice) is said once. A missing location leaves out its half ("17th &
 * Washington", or "to 17th & Mifflin"); none at all says "location not
 * given".
 *
 * @param {object} detour a detour object
 * @returns {string}
 */
export function detourPlaces(detour) {
  const { location_start: from, location_end: to } = detour;
  if (from !== null && to !== null && from !== to) {
    return `${from} to ${to}`;
  }
  if (from !== null) {
    return from;
  }
  if (to !== null) {
    return `to ${to}`;
  }
  return "location not given";
}

/**
 * One line for a detour not matched to a route ("Not on the map").
 *
 * e.g. "Route L, NB: Nedro & 20th St to Wister btwn Church & Spencer".
 * The direction is left out when null; places as `detourPlaces`.
 *
 * @param {object} detour a `status.unmatched` detour object
 * @returns {string}
 */
export function unmatchedSummary(detour) {
  const route = `Route ${apiRouteName(detour.route)}`;
  const head = detour.direction === null ? route : `${route}, ${detour.direction}`;
  return `${head}: ${detourPlaces(detour)}`;
}

/**
 * A detour's direction as the route names it: "Southbound".
 *
 * Looked up by `direction_id` in the route detail's `directions`. When
 * that's null (match couldn't tell, or its shapes disagree), not in the
 * list, or has no name, the API's own text is shown ("EB"); null when
 * there's neither.
 *
 * @param {object} detour a detour object
 * @param {{direction_id: number, name: string | null}[]} directions the
 *   route detail's `directions`
 * @returns {string | null}
 */
export function directionLabel(detour, directions) {
  // A null direction_id finds nothing: directions' ids are always 0 or 1.
  const named = directions.find((d) => d.direction_id === detour.direction_id);
  return named?.name ?? detour.direction;
}

/**
 * One direction for the route panel's header: "Southbound to 20th-Johnston".
 *
 * Just the name without a destination; "Direction 0" without a name
 * (the contract allows nulls; today's data has none).
 *
 * @param {{direction_id: number, name: string | null, destination: string | null}} direction
 * @returns {string}
 */
export function directionSummary({ direction_id: id, name, destination }) {
  const label = name ?? `Direction ${id}`;
  return destination === null ? label : `${label} to ${destination}`;
}

/**
 * A detour card's first line: "Southbound: 17th & Washington to 17th & Mifflin".
 *
 * Just the places when there's no direction.
 *
 * @param {object} detour a detour object
 * @param {{direction_id: number, name: string}[]} directions
 * @returns {string}
 */
export function detourHeadline(detour, directions) {
  const direction = directionLabel(detour, directions);
  const places = detourPlaces(detour);
  return direction === null ? places : `${direction}: ${places}`;
}

/** The route panel's heading for each `detourTiming` group. */
const TIMING_HEADINGS = Object.freeze({
  active: "In effect",
  upcoming: "Upcoming",
  unknown: "Dates unknown",
  ended: "Ended",
});

/**
 * A route panel group's heading with its count: "In effect (2)".
 *
 * @param {"active" | "upcoming" | "ended" | "unknown"} timing
 * @param {number} count detours in the group
 * @returns {string}
 */
export function timingHeading(timing, count) {
  return `${TIMING_HEADINGS[timing]} (${count})`;
}

/**
 * A sidebar row's detour count by timing: "3 now, 4 later".
 *
 * Parts come in a fixed order (now, later, ended, unknown) and zero parts
 * are left out, so a route with no detours gets "" (the row shows nothing).
 *
 * @param {{active: number, upcoming: number, ended: number, unknown: number}} counts
 *   from `timingCounts`
 * @returns {string}
 */
export function timingSummary(counts) {
  const parts = [
    [counts.active, TIMING_WORDS.active],
    [counts.upcoming, TIMING_WORDS.upcoming],
    [counts.ended, TIMING_WORDS.ended],
    [counts.unknown, TIMING_WORDS.unknown],
  ];
  return parts
    .filter(([count]) => count > 0)
    .map(([count, word]) => `${count} ${word}`)
    .join(", ");
}

/**
 * A map chooser button's text (the route badge sits beside it).
 *
 * A route choice: its long name (its label without one). A detour choice:
 * its card headline, "Loading…" until the route's detail file arrives
 * (`detail` null), "Detour not found" if the file doesn't have it.
 *
 * @param {{key: string, detour: string | null}} choice from `clickChoices`
 * @param {object} route the choice's routes.json entry
 * @param {object | null} detail its routes/<key>.json, or null while loading
 * @returns {string}
 */
export function choiceText(choice, route, detail) {
  if (choice.detour === null) {
    return route.long_name ?? routeLabel(route);
  }
  if (detail === null) {
    return "Loading\u2026";
  }
  const detour = detail.detours.find((d) => d.source_key === choice.detour);
  return detour === undefined ? "Detour not found" : detourHeadline(detour, detail.directions);
}

/**
 * What a screen reader hears when the focused route changes.
 *
 * "Route 21 Chestnut-Walnut: 3 now, 1 later." for a route (counts as on
 * its sidebar row), ": no detours." without any; "All routes." when
 * `route` is null (back to the overview).
 *
 * @param {object | null} route the focused routes.json entry, or null
 * @param {{active: number, upcoming: number, ended: number, unknown: number}} [counts]
 *   from `timingCounts`; needed with a route
 * @returns {string}
 */
export function focusAnnouncement(route, counts) {
  if (route === null) {
    return "All routes.";
  }
  const summary = timingSummary(counts);
  return `${routeLabel(route)}: ${summary === "" ? "no detours" : summary}.`;
}
