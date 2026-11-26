// Page bootstrap: build the map, load the data, draw it, report status.
//
// Loaded by index.html as a module, after maplibre-gl.js (so the global
// `maplibregl` exists for mapview.js).

import { loadSite, routeDetailLoader } from "./data.js";
import { statusLine } from "./format.js";
import { addOverviewLayers, addPopups, createMap } from "./mapview.js";
import { detouredRoutes, routesBounds, searchRoutes } from "./routes.js";
import { renderRouteList } from "./sidebar.js";

/** How often `now` moves on, so detours become active/ended on screen. */
const NOW_REFRESH_MS = 60_000;

/**
 * Show a short status line on the page.
 *
 * @param {string} message
 */
function showStatus(message) {
  // textContent (not innerHTML) so the message can't inject markup.
  document.getElementById("status").textContent = message;
}

/**
 * Show an error message on the page (and in the console).
 *
 * @param {string} message
 */
function showError(message) {
  console.error(message);
  document.getElementById("error").textContent = message;
}

/** Build the map, load the data, draw it, and zoom to the detours. */
async function main() {
  const map = createMap("map"); // the id of the <div>

  // The style loading and our data download are independent, so start both
  // and wait for both. `map.once("load")` with no callback returns a Promise.
  // Promise.all resolves to an array of results, in the order given; the
  // `[, site]` skips the first (the load event, which we don't need).
  const [, site] = await Promise.all([map.once("load"), loadSite()]);

  addOverviewLayers(map, site);
  addPopups(map, site.routes, routeDetailLoader());
  showStatus(statusLine(site.status));

  // Page state; moves to state.js in W4. Every change re-renders the list.
  const state = { now: new Date(), search: "" };
  const listElement = document.getElementById("route-list");
  const render = () =>
    renderRouteList(listElement, searchRoutes(site.routes, state.search), state.now);
  render();
  // "input" fires on every keystroke, and on the clear button / Escape.
  document.getElementById("search").addEventListener("input", (event) => {
    state.search = event.target.value;
    render();
  });
  setInterval(() => {
    state.now = new Date();
    render();
  }, NOW_REFRESH_MS);

  // Zoom to the detoured routes; with none, to the whole network. No
  // bounds at all (no shapes) leaves the map on Philadelphia.
  const bounds = routesBounds(detouredRoutes(site.routes)) ?? routesBounds(site.routes);
  if (bounds !== null) {
    map.fitBounds(bounds, { padding: 40, duration: 0 });
  }
}

// An async function returns a Promise; an error thrown inside it becomes a
// rejection, which `.catch` turns into a visible message instead of a
// silent console-only failure.
main().catch((err) => showError(err.message));
