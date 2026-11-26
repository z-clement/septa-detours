// Page bootstrap: build the map, load the data, then wire the state
// (state.js) to the map (mapview.js), the sidebar (sidebar.js) and the URL.
//
// Loaded by index.html as a module, after maplibre-gl.js (so the global
// `maplibregl` exists for mapview.js).

import { loadSite, routeDetailLoader } from "./data.js";
import { statusLine } from "./format.js";
import { addClickHandler, addOverviewLayers, createMap, fitRoute } from "./mapview.js";
import {
  detouredRoutes,
  groupByMode,
  routesBounds,
  searchRoutes,
  visibleRoutes,
} from "./routes.js";
import { createModeChips, renderRouteList, renderRoutePanel } from "./sidebar.js";
import { createState, formatHash, parseHash } from "./state.js";

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

/** Build the map, load the data, draw it, and wire up the page. */
async function main() {
  const map = createMap("map"); // the id of the <div>

  // The style loading and our data download are independent, so start both
  // and wait for both. `map.once("load")` with no callback returns a Promise.
  // Promise.all resolves to an array of results, in the order given; the
  // `[, site]` skips the first (the load event, which we don't need).
  const [, site] = await Promise.all([map.once("load"), loadSite()]);
  const routesByKey = new Map(site.routes.map((route) => [route.key, route]));
  const loadDetail = routeDetailLoader();

  const { showFocus, setHoveredDot, setSelectedDot } = addOverviewLayers(map, site);
  showStatus(statusLine(site.status));

  // The catalog's mode order (D8, as Python wrote it), for the chips and
  // the list's groups: search ranking must not reorder the groups.
  const modeOrder = groupByMode(site.routes).map((group) => group.mode);
  const store = createState({ modes: modeOrder, now: new Date() });

  // Zoom to the detoured routes; with none, to the whole network. No
  // bounds at all (no shapes) leaves the map on Philadelphia. Before the
  // hash is read, so a shared route link then moves on to its route.
  const bounds = routesBounds(detouredRoutes(site.routes)) ?? routesBounds(site.routes);
  if (bounds !== null) {
    map.fitBounds(bounds, { padding: 40, duration: 0 });
  }

  // --- The overview's list -------------------------------------------------

  const browseElement = document.getElementById("browse");
  const listElement = document.getElementById("route-list");
  const updateChips = createModeChips(
    document.getElementById("mode-chips"),
    modeOrder,
    store.toggleMode,
  );
  const renderList = ({ search, modes, now }) => {
    // A chip is greyed when the search alone has none of its mode (the
    // other chips don't count, or switching one off would grey it).
    const searched = searchRoutes(site.routes, search);
    updateChips(modes, new Set(searched.map((route) => route.mode)));
    // "Not on the map" only in the unfiltered list (decided): its detours
    // have no mode, and a search for "21" shouldn't end with route L's.
    const filtered = search.trim() !== "" || modes.size < modeOrder.length;
    renderRouteList(listElement, {
      routes: visibleRoutes(site.routes, search, modes),
      now,
      modeOrder,
      emptyText: modes.size === 0 ? "No modes selected." : "No routes match.",
      unmatched: filtered ? [] : site.status.unmatched,
    });
  };
  // "input" fires on every keystroke, and on the clear button / Escape.
  document.getElementById("search").addEventListener("input", (event) => {
    store.setSearch(event.target.value);
  });
  // One listener for every row (rows are rebuilt on each render).
  listElement.addEventListener("click", (event) => {
    const row = event.target.closest(".route-row");
    if (row !== null) {
      store.focus(row.dataset.key);
    }
  });

  // --- The focused route ---------------------------------------------------

  const panelElement = document.getElementById("route-panel");
  // The focused route's detail file as it loads: `detail` and `error`
  // stay null while loading. Kept outside the store: it's data, not a
  // choice the page's user made.
  let loaded = { key: null, detail: null, error: null };
  const renderFocus = (state) => {
    const detail = loaded.key === state.focus ? loaded.detail : null;
    showFocus(state.focus === null ? null : { key: state.focus, detail });
    if (state.focus !== null) {
      renderRoutePanel(panelElement, {
        route: routesByKey.get(state.focus),
        detail,
        error: loaded.key === state.focus ? loaded.error : null,
        now: state.now,
        selectedDetour: state.selectedDetour,
        onBack: () => store.focus(null),
      });
    }
  };
  const startLoading = (key) => {
    loaded = { key, detail: null, error: null };
    loadDetail(key)
      .then((detail) => {
        loaded = { key, detail, error: null };
      })
      .catch((err) => {
        loaded = { key, detail: null, error: err.message };
      })
      .finally(() => {
        // Dropped if the user has moved on to another route meanwhile.
        if (store.get().focus === key) {
          renderFocus(store.get());
        }
      });
  };
  addClickHandler(map, site.routes, loadDetail, store.focus);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && store.get().focus !== null) {
      store.focus(null);
    }
  });

  // --- The URL hash ---------------------------------------------------------

  // Hash -> state, on load and on Back/Forward. A route this catalog
  // doesn't have (an old link) is the overview. Both events can fire for
  // one step; the second changes nothing, so it notifies no one.
  const readHash = () => {
    const { focus, selectedDetour } = parseHash(window.location.hash);
    store.focus(routesByKey.has(focus) ? focus : null, selectedDetour);
  };
  window.addEventListener("hashchange", readHash);
  window.addEventListener("popstate", readHash);
  // State -> hash. A new route is a new history entry (so Back leaves
  // it); a new selection on the same route replaces the current one.
  // pushState/replaceState don't fire hashchange, so this doesn't loop.
  const writeHash = (state, changed) => {
    const hash = formatHash(state);
    if (hash === window.location.hash) {
      return;
    }
    // "" would keep the old hash; the bare path drops it.
    const url = hash === "" ? window.location.pathname + window.location.search : hash;
    if (changed.has("focus")) {
      window.history.pushState(null, "", url);
    } else {
      window.history.replaceState(null, "", url);
    }
  };

  // --- State -> everything --------------------------------------------------

  store.subscribe((state, changed) => {
    if (changed.has("focus") || changed.has("selectedDetour")) {
      writeHash(state, changed);
    }
    if (changed.has("focus")) {
      browseElement.hidden = state.focus !== null;
      panelElement.hidden = state.focus === null;
      if (state.focus !== null) {
        startLoading(state.focus);
        fitRoute(map, routesByKey.get(state.focus));
      }
    }
    // The list only while it's shown; returning to it redraws it.
    if (
      state.focus === null &&
      ["focus", "search", "modes", "now"].some((key) => changed.has(key))
    ) {
      renderList(state);
    }
    if (["focus", "selectedDetour", "now"].some((key) => changed.has(key))) {
      renderFocus(state);
    }
  });

  renderList(store.get());
  readHash();
  setInterval(() => store.setNow(new Date()), NOW_REFRESH_MS);
}

// An async function returns a Promise; an error thrown inside it becomes a
// rejection, which `.catch` turns into a visible message instead of a
// silent console-only failure.
main().catch((err) => showError(err.message));
