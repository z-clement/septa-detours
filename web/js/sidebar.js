// The sidebar's DOM: the route list (and, from W4, the route panel).
//
// Only builds elements; what goes in them comes from the PURE modules
// (routes.js, format.js), which have the tests. Text always goes in through
// `textContent`, never `innerHTML`, so names from the data can't inject markup.

import { modeLabel, timingSummary } from "./format.js";
import { detouredNow, groupByMode, timingCounts } from "./routes.js";

/**
 * A new element with an optional class and text.
 *
 * @param {string} tag
 * @param {string} [className]
 * @param {string} [text]
 * @returns {HTMLElement}
 */
function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className !== undefined) {
    node.className = className;
  }
  if (text !== undefined) {
    node.textContent = text;
  }
  return node;
}

/**
 * One route's row: badge, long name, detour count by timing.
 *
 * A `<button>` so it's focusable and clickable later (focus is W4; no
 * handler yet). Colours missing from the data (`null`) are left to the
 * CSS defaults rather than set here.
 *
 * @param {object} route a routes.json entry
 * @param {Date} now
 * @returns {HTMLButtonElement}
 */
function routeRow(route, now) {
  const row = element("button", "route-row");
  row.type = "button"; // not "submit", should it ever sit in a form
  row.dataset.key = route.key;
  if (!route.has_shapes) {
    row.classList.add("no-shapes");
    row.title = "No map lines for this route";
  }

  const badge = element("span", "badge", route.short_name);
  if (route.color !== null) {
    badge.style.backgroundColor = route.color;
  }
  if (route.text_color !== null) {
    badge.style.color = route.text_color;
  }

  row.append(
    badge,
    element("span", "name", route.long_name ?? ""),
    element("span", "count", timingSummary(timingCounts(route, now))),
  );
  return row;
}

/**
 * A titled list of route rows.
 *
 * @param {string} title
 * @param {object[]} routes routes.json entries, in display order
 * @param {Date} now
 * @returns {HTMLElement}
 */
function routeSection(title, routes, now) {
  const section = element("section", "route-section");
  section.append(element("h2", undefined, title), ...routes.map((route) => routeRow(route, now)));
  return section;
}

/**
 * Draw the route list into `container`, replacing what was there.
 *
 * "Detoured now" first (left out when no detour is active), then every
 * route grouped by mode. A route in "Detoured now" is also in its group.
 * Rebuilt whole on every call: 181 rows is cheap, and it avoids patching.
 * Draws whatever routes it's given: filtering (search) is the caller's.
 * No routes (nothing matched) shows a short message instead.
 *
 * @param {HTMLElement} container
 * @param {object[]} routes routes.json entries to show, in catalog order
 * @param {Date} now
 */
export function renderRouteList(container, routes, now) {
  if (routes.length === 0) {
    container.replaceChildren(element("p", "route-list-empty", "No routes match."));
    return;
  }
  const sections = [];
  const active = detouredNow(routes, now);
  if (active.length > 0) {
    sections.push(routeSection("Detoured now", active.map((row) => row.route), now));
  }
  for (const group of groupByMode(routes)) {
    sections.push(routeSection(modeLabel(group.mode), group.routes, now));
  }
  container.replaceChildren(...sections);
}
