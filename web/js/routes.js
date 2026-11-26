// Route catalog logic (routes.json entries).
//
// PURE: no DOM, no `maplibregl`, no fetch, so `node --test` can run it.

import { detourTiming } from "./detours.js";

/**
 * The routes with at least one matched detour, in catalog order.
 *
 * Counts every matched detour, placed or not: a route whose detours have
 * no start point is still detoured, and its line is drawn in color.
 *
 * @param {object[]} routes routes.json
 * @returns {object[]}
 */
export function detouredRoutes(routes) {
  return routes.filter((route) => route.detours.total > 0);
}

/**
 * Keys of `detouredRoutes`, for map filters.
 *
 * @param {object[]} routes routes.json
 * @returns {string[]}
 */
export function detouredKeys(routes) {
  return detouredRoutes(routes).map((route) => route.key);
}

/**
 * The box around every given route's bounds, as `map.fitBounds` takes it.
 *
 * Routes without shapes have `bounds: null` and are skipped.
 *
 * @param {object[]} routes routes.json entries
 * @returns {[[number, number], [number, number]] | null} null when no route
 *   has bounds
 */
export function routesBounds(routes) {
  const boxes = routes.map((route) => route.bounds).filter((bounds) => bounds !== null);
  if (boxes.length === 0) {
    return null;
  }
  return [
    [Math.min(...boxes.map((b) => b[0][0])), Math.min(...boxes.map((b) => b[0][1]))],
    [Math.max(...boxes.map((b) => b[1][0])), Math.max(...boxes.map((b) => b[1][1]))],
  ];
}

/**
 * How many of a route's matched detours are active, upcoming, ended or of
 * unknown timing at `now`, from its `routes.json` windows.
 *
 * Every matched detour has a window, placed or not, so the four counts add
 * up to `route.detours.total`.
 *
 * @param {object} route a routes.json entry
 * @param {Date} now
 * @returns {{active: number, upcoming: number, ended: number, unknown: number}}
 */
export function timingCounts(route, now) {
  const counts = { active: 0, upcoming: 0, ended: 0, unknown: 0 };
  for (const [start, end] of route.detours.windows) {
    counts[detourTiming(start, end, now)] += 1;
  }
  return counts;
}

/**
 * The sidebar's "Detoured now": routes with at least one active detour.
 *
 * Most active detours first; ties keep catalog order (`sort` is stable).
 * Routes whose detours are all upcoming, ended or unknown aren't here;
 * they're still in their mode's group with their counts.
 *
 * @param {object[]} routes routes.json
 * @param {Date} now
 * @returns {{route: object, active: number}[]}
 */
export function detouredNow(routes, now) {
  return routes
    .map((route) => ({ route, active: timingCounts(route, now).active }))
    .filter((row) => row.active > 0)
    .sort((a, b) => b.active - a.active);
}

/**
 * The sidebar's mode groups: routes split by `mode`, their order kept.
 *
 * Groups come in `modeOrder`'s order, then any other mode in order of its
 * first route. With the default (no order given) that's every mode by its
 * first route, so grouping the whole catalog gives the order Python wrote
 * into routes.json (not repeated here). Pass that catalog order when
 * grouping search results: ranking puts route K first for "k", which
 * mustn't move Buses above Metro. Only modes with routes get a group. A
 * mode that appears in two runs is still one group, its routes in order.
 *
 * @param {object[]} routes routes.json (or any subset, e.g. search results)
 * @param {string[]} [modeOrder] modes in display order, e.g.
 *   `groupByMode(catalog).map((g) => g.mode)`
 * @returns {{mode: string, routes: object[]}[]}
 */
export function groupByMode(routes, modeOrder = []) {
  // Insertion order: modeOrder first, then other modes as they appear.
  const groups = new Map(modeOrder.map((mode) => [mode, []]));
  for (const route of routes) {
    if (!groups.has(route.mode)) {
      groups.set(route.mode, []);
    }
    groups.get(route.mode).push(route);
  }
  return [...groups]
    .filter(([, members]) => members.length > 0)
    .map(([mode, members]) => ({ mode, routes: members }));
}

/**
 * The sidebar search: routes whose names match `query`, best matches first.
 *
 * Case is ignored and the query is trimmed; a blank query keeps every
 * route. A number (digits only) is a route number: it matches only at the
 * start of `short_name`, so "2" finds 2, 21 and 204 but not 12, and not
 * route 5 ("2nd-Market to ...": long names are full of street numbers).
 * Anything else matches anywhere in `short_name` or `long_name`: "owl"
 * finds L1 OWL and B1 OWL, "chest" finds 23 (... to Chestnut Hill). A
 * `null` long name never matches.
 *
 * Order: routes whose `short_name` starts with the query first, then the
 * other matches, each in catalog order. So "k" puts route K before the
 * 61 routes with a "k" in their names (Frankford, Park, ...). Every
 * number match starts with the query, so numbers stay in catalog order.
 *
 * @param {object[]} routes routes.json
 * @param {string} query what the user typed
 * @returns {object[]}
 */
export function searchRoutes(routes, query) {
  const needle = query.trim().toLowerCase();
  if (needle === "") {
    return [...routes];
  }
  if (/^[0-9]+$/.test(needle)) {
    return routes.filter((route) => route.short_name.startsWith(needle)); // digits: no case
  }
  const contains = (name) => name !== null && name.toLowerCase().includes(needle);
  const matches = routes.filter((route) => contains(route.short_name) || contains(route.long_name));
  const startsWith = (route) => route.short_name.toLowerCase().startsWith(needle);
  return [...matches.filter(startsWith), ...matches.filter((route) => !startsWith(route))];
}

/**
 * The routes the sidebar lists: those matching the search whose mode is on.
 *
 * A route must pass both (`searchRoutes` and the mode chips). Catalog
 * order kept. No modes on lists nothing, whatever the search.
 *
 * @param {object[]} routes routes.json
 * @param {string} query what the user typed
 * @param {Set<string>} modes the modes whose chips are on
 * @returns {object[]}
 */
export function visibleRoutes(routes, query, modes) {
  return searchRoutes(routes, query).filter((route) => modes.has(route.mode));
}

/**
 * What a map click could mean: one choice per detour or route under it.
 *
 * Dots win: when any start dot was hit, lines don't count (a dot sits on
 * its route's line), and each distinct detour is a choice (direction
 * twins sharing a `source_key` and a dot collapse into one). With no
 * dots, each distinct route among the lines is a choice, with no detour.
 * Choices keep the order first seen (MapLibre lists the topmost first).
 *
 * @param {{properties: {key: string, source_key?: string}}[]} dots
 *   detour features under the click: start dots and skipped stretches
 *   (a detour's dot and stretch both hit are one choice)
 * @param {{properties: {key: string}}[]} lines line features under the click
 * @returns {{key: string, detour: string | null}[]}
 */
export function clickChoices(dots, lines) {
  // Keyed by identity; setting a key again keeps its first position (and
  // the value is the same), so a repeat changes nothing.
  const choices = new Map();
  if (dots.length > 0) {
    for (const { properties: p } of dots) {
      // JSON of both: a separator character could appear inside a value.
      choices.set(JSON.stringify([p.key, p.source_key]), { key: p.key, detour: p.source_key });
    }
  } else {
    for (const { properties: p } of lines) {
      choices.set(p.key, { key: p.key, detour: null });
    }
  }
  return [...choices.values()];
}

/**
 * A copy of a detour feature collection (starts.geojson) whose features
 * also carry `label`: their route's short name ("49", "L1 OWL"), for the
 * map's route-number markers (UI plan B1).
 *
 * A feature whose route isn't in `routes` (shouldn't happen: export
 * checks) is labelled with its key, so it still shows. The input isn't
 * changed.
 *
 * @param {{type: string, features: object[]}} collection
 * @param {object[]} routes routes.json (`key`, `short_name`)
 * @returns {{type: string, features: object[]}}
 */
export function withRouteLabels(collection, routes) {
  const names = new Map(routes.map((route) => [route.key, route.short_name]));
  return {
    ...collection,
    features: collection.features.map((feature) => ({
      ...feature,
      properties: {
        ...feature.properties,
        label: names.get(feature.properties.key) ?? feature.properties.key,
      },
    })),
  };
}
