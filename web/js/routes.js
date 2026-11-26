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
 * The sidebar's mode groups: routes split by `mode`, catalog order kept.
 *
 * Groups come in order of each mode's first route, so the mode order is
 * the one Python wrote into routes.json (not repeated here). Only modes
 * with routes get a group. A mode that appears in two runs is still one
 * group, its routes in catalog order.
 *
 * @param {object[]} routes routes.json (or any subset, e.g. search results)
 * @returns {{mode: string, routes: object[]}[]}
 */
export function groupByMode(routes) {
  const groups = new Map(); // insertion order = first appearance
  for (const route of routes) {
    if (!groups.has(route.mode)) {
      groups.set(route.mode, []);
    }
    groups.get(route.mode).push(route);
  }
  return [...groups].map(([mode, members]) => ({ mode, routes: members }));
}
