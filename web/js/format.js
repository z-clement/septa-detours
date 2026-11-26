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

/**
 * Popup text for one detour (a detour object from routes/<key>.json).
 *
 * Plain JSON keeps missing values as explicit `null` (unlike clicked
 * features), and `issues` is a list.
 *
 * @param {object} detour a detour object
 * @param {object} route its routes.json entry
 * @returns {string}
 */
export function describeDetour(detour, route) {
  const issues = detour.issues.length > 0 ? detour.issues.join("; ") : "(none)";
  const node =
    detour.start_point === null ? "not placed" : `OSM node ${detour.start_point.node_id}`;
  return [
    `${routeLabel(route)}, ${detour.direction ?? "(no direction)"}`,
    `From: ${detour.location_start ?? "(unknown)"}`,
    `To: ${detour.location_end ?? "(unknown)"}`,
    `${formatTime(detour.start)} to ${formatTime(detour.end)}`,
    `Reason: ${detour.reason ?? "(none given)"}`,
    `Status: ${detour.status}`,
    `Issues: ${issues}`,
    "",
    detour.message,
    "",
    `source_key ${detour.source_key}, ${node}`,
  ].join("\n");
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
    [counts.active, "now"],
    [counts.upcoming, "later"],
    [counts.ended, "ended"],
    [counts.unknown, "unknown"],
  ];
  return parts
    .filter(([count]) => count > 0)
    .map(([count, word]) => `${count} ${word}`)
    .join(", ");
}

/**
 * Popup text for a route line: its name and its detours.
 *
 * @param {object} route a routes.json entry
 * @returns {string}
 */
export function describeRoute(route) {
  const { total, placed } = route.detours;
  const detours =
    total === 0 ? "No detours" : `${plural(total, "detour")} (${placed} on the map)`;
  return `${routeLabel(route)}\n${detours}`;
}
