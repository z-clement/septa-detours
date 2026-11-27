// Page bootstrap: build the map, load the data, then wire the state
// (state.js) to the map (mapview.js), the sidebar (sidebar.js) and the URL.
//
// Loaded by index.html as a module, after maplibre-gl.js (so the global
// `maplibregl` exists for mapview.js).

import { loadSite, routeDetailLoader } from "./data.js";
import { detourBounds, inEffectKeys, isInEffect, rejoinCollection } from "./detours.js";
import { focusAnnouncement, staleNotice, statusLine } from "./format.js";
import {
  addClickHandler,
  addLegend,
  addOverviewLayers,
  createMap,
  fitPadding,
  fitDetours,
  fitRoute,
} from "./mapview.js";
import {
  detouredRoutes,
  groupByMode,
  routeMarkers,
  routesBounds,
  searchRoutes,
  timingCounts,
  visibleRoutes,
} from "./routes.js";
import { SHEET_HEIGHTS, nextSheet, sheetHeightPx } from "./sheet.js";
import { createModeChips, renderRouteList, renderRoutePanel } from "./sidebar.js";
import { createState, formatHash, parseHash } from "./state.js";

/** How often `now` moves on, so detours become active/ended on screen. */
const NOW_REFRESH_MS = 60_000;

/** Where the sidebar becomes a bottom sheet; the same width as app.css. */
const NARROW = window.matchMedia("(max-width: 699px)");

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
  const loadDetail = routeDetailLoader(site.status.generated_at);

  const { showFocus, setInEffect, setMarkers, setHoveredDot, setSelectedDot } =
    addOverviewLayers(map, site);
  // Open on wide screens; a closed "Map key" button on phones (U6).
  const { showLegendFor } = addLegend(map, { open: !NARROW.matches });
  showStatus(statusLine(site.status));
  const staleElement = document.getElementById("stale");
  /** The old-data banner at `now` (empty, so hidden, while fresh). Only
   * rewritten when the text changes: the clock ticks every minute, and a
   * screen reader may announce a rewritten role="status" again. */
  const showStale = (now) => {
    const text = staleNotice(site.status, now) ?? "";
    if (staleElement.textContent !== text) {
      staleElement.textContent = text;
    }
  };

  // The catalog's mode order (D8, as Python wrote it), for the chips and
  // the list's groups: search ranking must not reorder the groups.
  const modeOrder = groupByMode(site.routes).map((group) => group.mode);
  const store = createState({ modes: modeOrder, now: new Date() });
  showStale(store.get().now);

  // The map draws only detours in effect, by the page's clock (U1): every
  // detour feature carries its start and end.
  const detourFeatures = [
    ...site.starts.features,
    ...site.skipped.features,
    ...site.paths.features,
  ];
  const showInEffect = (now) => {
    const keys = inEffectKeys(detourFeatures, now);
    setInEffect(keys);
    setMarkers(routeMarkers(site.starts.features, keys, site.routes));
  };
  showInEffect(store.get().now);

  // --- The mobile sheet -----------------------------------------------------

  // Pixels the sheet hides at the map's bottom: 0 on wide screens.
  const coverBottom = () =>
    NARROW.matches ? sheetHeightPx(store.get().sheet, window.innerHeight) : 0;
  const handle = document.getElementById("sheet-handle");
  const sidebar = document.getElementById("sidebar");
  const applySheet = ({ sheet }) => {
    sidebar.dataset.sheet = sheet; // app.css hides all but the status at peek
    // On <html>: the sheet and MapLibre's bottom controls both read it.
    document.documentElement.style.setProperty(
      "--sheet-height",
      `${sheetHeightPx(sheet, window.innerHeight)}px`,
    );
    // Whether the next tap raises or lowers it.
    const raises = SHEET_HEIGHTS.indexOf(nextSheet(sheet)) > SHEET_HEIGHTS.indexOf(sheet);
    handle.setAttribute("aria-label", raises ? "Show more of the panel" : "Show less of the panel");
    handle.setAttribute("aria-expanded", String(sheet !== "peek"));
  };
  applySheet(store.get());
  handle.addEventListener("click", store.cycleSheet);
  // Heights are fractions of the viewport (rotation, the URL bar).
  window.addEventListener("resize", () => applySheet(store.get()));

  // Zoom to the detoured routes; with none, to the whole network. No
  // bounds at all (no shapes) leaves the map on Philadelphia. Before the
  // hash is read, so a shared route link then moves on to its route.
  const bounds = routesBounds(detouredRoutes(site.routes)) ?? routesBounds(site.routes);
  if (bounds !== null) {
    map.fitBounds(bounds, { padding: fitPadding(coverBottom()), duration: 0 });
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
  const searchElement = document.getElementById("search");
  searchElement.addEventListener("input", (event) => {
    store.setSearch(event.target.value);
  });
  // Typing on a phone: the keyboard takes half the screen, so the sheet
  // goes full (decided). Harmless on wide screens (no sheet there).
  searchElement.addEventListener("focus", () => store.raiseSheet("full"));
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
    const rejoins =
      detail === null
        ? null
        : rejoinCollection(detail, routesByKey.get(state.focus)?.color ?? null, state.now);
    showFocus(state.focus === null ? null : { key: state.focus, detail, rejoins });
    if (state.focus !== null) {
      renderRoutePanel(panelElement, {
        route: routesByKey.get(state.focus),
        detail,
        error: loaded.key === state.focus ? loaded.error : null,
        now: state.now,
        selectedDetour: state.selectedDetour,
        onBack: () => store.focus(null),
        onWholeRoute: () => fitRoute(map, routesByKey.get(store.get().focus), coverBottom()),
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
          frameFocus(store.get());
          scrollToSelected(store.get()); // a shared link's detour
        }
      });
  };
  // The selected detour's card, scrolled into view only as far as needed
  // ("nearest": a card already in view, e.g. the one clicked, stays put).
  // Twins share a source_key; the first is enough.
  const scrollToSelected = ({ selectedDetour }) => {
    if (selectedDetour !== null) {
      panelElement
        .querySelector(`.detour-card[data-source-key="${CSS.escape(selectedDetour)}"]`)
        ?.scrollIntoView({ block: "nearest" });
    }
  };
  // The focused route's detours, from its detail file (dots carry no
  // detour data); [] while it loads. Twins share a source_key: both count.
  const focusedDetours = (focus) => (loaded.key === focus ? loaded.detail : null)?.detours ?? [];
  const selectedDetours = ({ focus, selectedDetour }) =>
    focusedDetours(focus).filter((d) => d.source_key === selectedDetour);
  // The camera when a route's detail arrives (UI plan C1): the selected
  // detour (a shared link), else the detours in effect, else the whole
  // route (none in effect, none placed, or the detail didn't load).
  const frameFocus = (state) => {
    const inEffect = focusedDetours(state.focus).filter((d) =>
      isInEffect(d.start, d.end, state.now, d.hours),
    );
    const bounds = detourBounds(selectedDetours(state)) ?? detourBounds(inEffect);
    if (bounds !== null) {
      fitDetours(map, bounds, coverBottom());
    } else {
      fitRoute(map, routesByKey.get(state.focus), coverBottom());
    }
  };
  // A new selection on the same route: the camera to that detour. An
  // unplaced one (no geometry) leaves the camera where it is.
  const zoomToSelected = (state) => {
    const bounds = detourBounds(selectedDetours(state));
    if (bounds !== null) {
      fitDetours(map, bounds, coverBottom());
    }
  };
  // Cards: one listener each for the whole panel (cards are rebuilt on
  // each render). A click anywhere on a card selects it, except inside
  // its "Parser notes", which only opens and closes them.
  panelElement.addEventListener("click", (event) => {
    const card = event.target.closest(".detour-card");
    if (card !== null && event.target.closest(".issues") === null) {
      store.focus(store.get().focus, card.dataset.sourceKey);
    }
  });
  panelElement.addEventListener("mouseover", (event) => {
    setHoveredDot(event.target.closest(".detour-card")?.dataset.sourceKey ?? null);
  });
  panelElement.addEventListener("mouseleave", () => setHoveredDot(null));
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

  const announceElement = document.getElementById("announce");
  // The route the panel showed before this change, to return keyboard
  // focus to its row when leaving it.
  let shownFocus = null;

  store.subscribe((state, changed) => {
    // Before the panel is hidden: was the keyboard in it?
    const keyboardInPanel = panelElement.contains(document.activeElement);
    if (changed.has("sheet")) {
      applySheet(state);
    }
    if (changed.has("focus") || changed.has("selectedDetour")) {
      writeHash(state, changed);
    }
    if (changed.has("focus")) {
      browseElement.hidden = state.focus !== null;
      panelElement.hidden = state.focus === null;
      // The hovered card is gone (removed cards fire no mouseleave).
      setHoveredDot(null);
      showLegendFor(state.focus === null ? null : routesByKey.get(state.focus));
      if (state.focus !== null) {
        // The camera moves when the detail arrives (frameFocus).
        startLoading(state.focus);
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
    if (changed.has("now")) {
      showInEffect(state.now);
      showStale(state.now);
    }
    if (changed.has("focus")) {
      const route = state.focus === null ? null : routesByKey.get(state.focus);
      announceElement.textContent = focusAnnouncement(
        route,
        route === null ? undefined : timingCounts(route, state.now),
      );
      if (state.focus !== null) {
        // Keyboard users land at the panel's start; the title isn't a
        // Tab stop, so Tab then reaches Back and the cards.
        document.getElementById("route-panel-title").focus({ preventScroll: true });
      } else if (keyboardInPanel) {
        // Back (button, Escape, or browser): to the route's row, or the
        // search box when the filters hide it. Not the search box on a
        // phone: focusing it raises the sheet to full.
        const row = listElement.querySelector(
          `.route-row[data-key="${CSS.escape(shownFocus)}"]`,
        );
        if (row !== null) {
          row.focus();
        } else if (!NARROW.matches) {
          searchElement.focus();
        }
      }
      shownFocus = state.focus;
    }
    if (changed.has("selectedDetour")) {
      setSelectedDot(state.selectedDetour);
      scrollToSelected(state);
      // A new route frames itself when its detail arrives (frameFocus).
      if (!changed.has("focus") && state.selectedDetour !== null) {
        zoomToSelected(state);
      }
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
