// Route catalog logic (routes.json entries).
//
// PURE: no DOM, no `maplibregl`, no fetch, so `node --test` can run it.

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
