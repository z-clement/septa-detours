// Everything that touches MapLibre: the map, its layers, popups.
// The only module that uses the global `maplibregl` (from the UMD script
// in index.html).

import { element, routeBadge } from "./dom.js";
import { choiceText } from "./format.js";
import { clickChoices, detouredKeys } from "./routes.js";

const BASEMAP_STYLE = "https://tiles.openfreemap.org/styles/positron";

/** Used when a route's `color` is null (export emits null, never junk). */
const FALLBACK_COLOR = "#555555";

/** The faint whole-network lines (decided: one neutral grey, not route colors). */
const NETWORK_COLOR = "#9aa0a6";

/** Start dots of detours that have ended. */
const ENDED_COLOR = "#9e9e9e";

/** The ring around the selected detour's dot. */
const SELECTED_RING_COLOR = "#111111";

/** The wash over a skipped stretch: white at this opacity leaves the route
 * line showing at about a third of its color. app.css's legend repeats it. */
const SKIPPED_FADE_OPACITY = 0.65;

/** Rough centre of Philadelphia, [lon, lat], shown before the data arrives. */
const PHILLY_CENTER = [-75.16, 39.95];

/** The network's opacity on the overview, and fainter while a route is focused. */
const NETWORK_OPACITY = 0.6;
const NETWORK_OPACITY_FOCUSED = 0.3;

const NETWORK_SOURCE = "network";
const STARTS_SOURCE = "starts";
const SKIPPED_SOURCE = "skipped";
const FOCUS_SOURCE = "focus";
const NETWORK_LAYER = "network-lines";
const DETOURED_LAYER = "detoured-lines";
const FOCUS_LAYER = "focus-lines";
const SKIPPED_LAYER = "skipped-fade";
const STARTS_LAYER = "start-dots";

/** Sources whose features are detours (`key` + `source_key`): their
 * hover/selected feature-state goes on both. */
const DETOUR_SOURCES = [STARTS_SOURCE, SKIPPED_SOURCE];

const EMPTY_COLLECTION = Object.freeze({ type: "FeatureCollection", features: [] });

/**
 * Create the map in the element with id `container`, with zoom buttons.
 *
 * @param {string} container the id of the <div>
 * @returns {maplibregl.Map}
 */
export function createMap(container) {
  const map = new maplibregl.Map({
    container,
    style: BASEMAP_STYLE,
    center: PHILLY_CENTER,
    zoom: 11,
  });
  map.addControl(new maplibregl.NavigationControl());
  return map;
}

/**
 * Draw the overview: the whole network faintly, detoured routes in color,
 * the stretch each detour in effect skips faded out, and every placed
 * detour's start point on top. Returns the functions
 * that change it afterwards: `showFocus` (the overview or one focused
 * route) and the dot highlights `setHoveredDot` / `setSelectedDot`.
 *
 * Must run after the style has loaded (adding a source before then throws).
 * Layers draw in the order they're added: network, detoured, the focused
 * route (empty until one is focused), the fade over skipped stretches,
 * dots.
 *
 * Expressions: MapLibre styles are small programs written as JSON arrays,
 * evaluated per feature. `["get", "color"]` reads a property; `coalesce`
 * takes the first non-null value; `match` picks a value by a property's
 * value, with the last item as the default.
 *
 * Directions: `line-offset` shifts a line sideways relative to the order its
 * vertices are drawn in (positive = to the right of travel). A route's two
 * directions are drawn in opposite orders, so the *same* positive offset
 * puts each one on its own side of the street (US right-hand traffic, like
 * the real buses), and they stop hiding each other. Known gap: a shape
 * used by both directions has identical geometry *and* vertex order, so
 * the offset can't separate its two lines.
 *
 * @param {maplibregl.Map} map
 * @param {{routes: object[], network: object, starts: object, skipped: object}} site
 * @returns {{
 *   showFocus: (focus: {key: string, detail: object | null} | null) => void,
 *   setHoveredDot: (sourceKey: string | null) => void,
 *   setSelectedDot: (sourceKey: string | null) => void,
 * }} see each below
 */
export function addOverviewLayers(map, site) {
  map.addSource(NETWORK_SOURCE, { type: "geojson", data: site.network });
  // promoteId: each dot's id is its detour's source_key, so a dot can be
  // found again for feature-state (hover/selected). Direction twins share
  // a key, and a dot: both light up together.
  map.addSource(STARTS_SOURCE, {
    type: "geojson",
    data: site.starts,
    promoteId: "source_key",
  });
  map.addSource(SKIPPED_SOURCE, {
    type: "geojson",
    data: site.skipped,
    promoteId: "source_key",
  });
  map.addSource(FOCUS_SOURCE, { type: "geojson", data: EMPTY_COLLECTION });

  const routeColor = ["coalesce", ["get", "color"], FALLBACK_COLOR];
  const offset = ["interpolate", ["linear"], ["zoom"], 10, 1, 16, 4];
  const lineLayout = { "line-cap": "round", "line-join": "round" };

  map.addLayer({
    id: NETWORK_LAYER,
    type: "line",
    source: NETWORK_SOURCE,
    layout: lineLayout,
    paint: {
      "line-color": NETWORK_COLOR,
      "line-opacity": NETWORK_OPACITY,
      // `interpolate` over `zoom`: thin when zoomed out, wider when zoomed
      // in (pairs are zoom, value).
      "line-width": ["interpolate", ["linear"], ["zoom"], 10, 0.75, 16, 2.5],
      "line-offset": offset,
    },
  });

  // The same lines again, only for detoured routes, in their own color.
  // `["literal", [...]]` marks the array as data, not an expression.
  const detouredFilter = ["in", ["get", "key"], ["literal", detouredKeys(site.routes)]];
  map.addLayer({
    id: DETOURED_LAYER,
    type: "line",
    source: NETWORK_SOURCE,
    filter: detouredFilter,
    layout: lineLayout,
    paint: {
      "line-color": routeColor,
      "line-width": ["interpolate", ["linear"], ["zoom"], 10, 1.5, 16, 5],
      "line-offset": offset,
    },
  });

  // The focused route's every shape (route detail, not the network's
  // covering set): covering shapes as thick as detoured lines, short-turns
  // and branches thinner. Empty on the overview.
  map.addLayer({
    id: FOCUS_LAYER,
    type: "line",
    source: FOCUS_SOURCE,
    layout: lineLayout,
    paint: {
      "line-color": routeColor,
      "line-width": [
        "interpolate",
        ["linear"],
        ["zoom"],
        10,
        ["case", ["get", "covering"], 2, 1],
        16,
        ["case", ["get", "covering"], 6, 3],
      ],
      "line-offset": offset,
    },
  });

  // Hovered (a card under the pointer) or selected: bigger, and selected
  // gets a dark ring. `feature-state` is set per detour by the setters
  // below, on its dot and its stretch alike (the fade doesn't use it).
  const hovered = ["boolean", ["feature-state", "hover"], false];
  const selected = ["boolean", ["feature-state", "selected"], false];
  const emphasized = ["any", hovered, selected];

  // The stretch of regular route each detour skips (tier B), faded out:
  // a semi-transparent white line over the route (still drawn whole
  // underneath), a little wider than it so its edges fade too. Butt caps,
  // so the fade ends exactly at the start and rejoin points. Same offset
  // as the route lines: a stretch is cut from its direction's shape, in
  // travel order, so it lands on that side.
  //
  // Only detours in effect (active, or unknown like the dots): an upcoming
  // or ended detour's stretch is served right now.
  const skippedFilter = ["match", ["get", "timing"], ["upcoming", "ended"], false, true];
  map.addLayer({
    id: SKIPPED_LAYER,
    type: "line",
    source: SKIPPED_SOURCE,
    filter: skippedFilter,
    layout: { "line-cap": "butt", "line-join": "round" },
    paint: {
      "line-color": "#ffffff",
      "line-opacity": SKIPPED_FADE_OPACITY,
      "line-width": ["interpolate", ["linear"], ["zoom"], 10, 3, 16, 8],
      "line-offset": offset,
    },
  });

  // Styled by `timing` (computed at export time; the page will recompute
  // it in W3): active solid in the route color, upcoming hollow (white
  // fill, route-color ring), ended grey. `unknown` looks like active.
  map.addLayer({
    id: STARTS_LAYER,
    type: "circle",
    source: STARTS_SOURCE,
    paint: {
      "circle-color": [
        "match",
        ["get", "timing"],
        "upcoming",
        "#ffffff",
        "ended",
        ENDED_COLOR,
        routeColor,
      ],
      // `zoom` must be interpolate's input, so the state goes in each stop.
      "circle-radius": [
        "interpolate",
        ["linear"],
        ["zoom"],
        10,
        ["case", emphasized, 7, 4],
        16,
        ["case", emphasized, 13, 9],
      ],
      "circle-stroke-color": [
        "case",
        selected,
        SELECTED_RING_COLOR,
        ["match", ["get", "timing"], "upcoming", routeColor, "#ffffff"],
      ],
      "circle-stroke-width": ["case", selected, 3, 2],
    },
  });

  /**
   * Show the overview (`null`) or one focused route.
   *
   * Focused: the network fainter, other routes' colored lines and dots
   * hidden, the route's own dots kept. Its shapes come from `detail`;
   * while that's loading (null), its network lines stay in color so the
   * route doesn't vanish meanwhile. Doesn't move the camera (`fitRoute`).
   *
   * @param {{key: string, detail: object | null} | null} focus
   */
  function showFocus(focus) {
    const only = focus === null ? null : ["==", ["get", "key"], focus.key];
    const detail = focus === null ? null : focus.detail;
    map.setPaintProperty(
      NETWORK_LAYER,
      "line-opacity",
      focus === null ? NETWORK_OPACITY : NETWORK_OPACITY_FOCUSED,
    );
    map.setFilter(DETOURED_LAYER, only ?? detouredFilter);
    map.setLayoutProperty(DETOURED_LAYER, "visibility", detail === null ? "visible" : "none");
    map.setFilter(STARTS_LAYER, only);
    map.setFilter(SKIPPED_LAYER, only === null ? skippedFilter : ["all", only, skippedFilter]);
    map.getSource(FOCUS_SOURCE).setData(detail === null ? EMPTY_COLLECTION : detail.shapes);
  }

  return {
    showFocus,
    setHoveredDot: dotStateSetter(map, "hover"),
    setSelectedDot: dotStateSetter(map, "selected"),
  };
}

/**
 * A setter that puts feature-state `name` on one detour at a time: its
 * start dot and its skipped stretch (`DETOUR_SOURCES`).
 *
 * Each call clears it from the previous detour. A key with no dot or no
 * stretch just clears: feature-state on a missing id is ignored.
 *
 * @param {maplibregl.Map} map
 * @param {string} name the feature-state key ("hover", "selected")
 * @returns {(sourceKey: string | null) => void}
 */
function dotStateSetter(map, name) {
  let current = null;
  return (sourceKey) => {
    for (const source of DETOUR_SOURCES) {
      if (current !== null) {
        map.setFeatureState({ source, id: current }, { [name]: false });
      }
      if (sourceKey !== null) {
        map.setFeatureState({ source, id: sourceKey }, { [name]: true });
      }
    }
    current = sourceKey;
  };
}

/**
 * Pan the map to a detour's start point if it isn't visible; no zoom.
 *
 * Visible means inside the map and above the bottom `coverBottom` pixels
 * (the mobile sheet). The pan centres the dot in that visible part: the
 * offset moves it up by half the cover.
 *
 * @param {maplibregl.Map} map
 * @param {{lon: number, lat: number}} point a detour's `start_point`
 * @param {number} [coverBottom] pixels hidden at the map's bottom
 */
export function panToDot(map, { lon, lat }, coverBottom = 0) {
  const { x, y } = map.project([lon, lat]);
  const { clientWidth: width, clientHeight: height } = map.getContainer();
  if (x < 0 || x > width || y < 0 || y > height - coverBottom) {
    map.panTo([lon, lat], { offset: [0, -coverBottom / 2] });
  }
}

/** Room left around fitted lines, in CSS pixels. */
const FIT_PADDING_PX = 40;

/**
 * fitBounds padding that also clears `coverBottom` pixels at the bottom
 * (the mobile sheet over the map; 0 on wide screens).
 *
 * @param {number} coverBottom
 * @returns {{top: number, right: number, bottom: number, left: number}}
 */
export function fitPadding(coverBottom) {
  const p = FIT_PADDING_PX;
  return { top: p, right: p, bottom: p + coverBottom, left: p };
}

/**
 * A small key to the map's line styles, top left (a MapLibre control, so
 * the map places it on every screen size).
 *
 * @param {maplibregl.Map} map
 */
export function addLegend(map) {
  const legend = element("div", "maplibregl-ctrl legend");
  legend.setAttribute("aria-label", "Map key");
  const row = (swatchClass, text) => {
    const item = element("div", "legend-row");
    const swatch = element("span", `legend-swatch ${swatchClass}`);
    swatch.setAttribute("aria-hidden", "true");
    item.append(swatch, element("span", undefined, text));
    return item;
  };
  legend.append(
    row("legend-route", "Detoured route"),
    row("legend-skipped", "Skipped by a detour"),
    row("legend-start", "Detour starts here"),
  );
  map.addControl(
    {
      onAdd: () => legend,
      onRemove: () => legend.remove(),
    },
    "top-left",
  );
}

/**
 * Move the camera to a route's lines (animated), clear of the sheet. A
 * route without shapes (`bounds` null) leaves the camera where it is.
 *
 * @param {maplibregl.Map} map
 * @param {object} route a routes.json entry
 * @param {number} [coverBottom] pixels hidden at the map's bottom
 */
export function fitRoute(map, route, coverBottom = 0) {
  if (route.bounds !== null) {
    map.fitBounds(route.bounds, { padding: fitPadding(coverBottom) });
  }
}

/**
 * The chooser's content: one button per choice (route badge + text).
 *
 * Route choices are labelled at once; detour choices say "Loading…"
 * until their route's detail file arrives (one fetch per route, cached by
 * `loadDetail`), then show the card headline.
 *
 * @param {{key: string, detour: string | null}[]} choices from `clickChoices`
 * @param {Map<string, object>} routesByKey routes.json by key
 * @param {(key: string) => Promise<object>} loadDetail
 * @param {(choice: {key: string, detour: string | null}) => void} onPick
 * @returns {HTMLElement}
 */
function chooserContent(choices, routesByKey, loadDetail, onPick) {
  const list = element("div", "chooser");
  for (const choice of choices) {
    const route = routesByKey.get(choice.key);
    const text = element("span", "name", choiceText(choice, route, null));
    const button = element("button", "chooser-choice");
    button.type = "button";
    button.append(routeBadge(route), text);
    button.addEventListener("click", () => onPick(choice));
    list.append(button);
    if (choice.detour !== null) {
      loadDetail(choice.key)
        .then((detail) => {
          text.textContent = choiceText(choice, route, detail);
        })
        .catch((err) => {
          text.textContent = err.message;
        });
    }
  }
  return list;
}

/**
 * Clicks on the map: focus the route clicked, or offer a chooser.
 *
 * One handler for the whole map instead of one per layer: a start dot
 * usually sits on its route line, and per-layer handlers would fire twice
 * for one click. `queryRenderedFeatures` returns every drawn feature
 * under the click; `clickChoices` turns them into choices (dots win over
 * lines). When every choice is on one route, that route is focused
 * directly (with the first choice's detour, if dots were hit). Several
 * routes get a chooser popup instead of a guess: one button per detour
 * (dots) or per route (lines). Also a pointer cursor over anything
 * clickable.
 *
 * @param {maplibregl.Map} map
 * @param {object[]} routes routes.json
 * @param {(key: string) => Promise<object>} loadDetail
 * @param {(key: string, detour: string | null) => void} onFocus
 */
export function addClickHandler(map, routes, loadDetail, onFocus) {
  const routesByKey = new Map(routes.map((route) => [route.key, route]));
  let popup = null;

  map.on("click", (event) => {
    popup?.remove();
    // A skipped stretch is a detour too (key + source_key): it counts as
    // a dot, selecting its detour.
    const dots = map.queryRenderedFeatures(event.point, {
      layers: [STARTS_LAYER, SKIPPED_LAYER],
    });
    const lines =
      dots.length > 0
        ? []
        : map.queryRenderedFeatures(event.point, { layers: [DETOURED_LAYER, NETWORK_LAYER] });
    const choices = clickChoices(dots, lines);
    if (choices.length === 0) {
      return;
    }
    if (new Set(choices.map((choice) => choice.key)).size === 1) {
      onFocus(choices[0].key, choices[0].detour);
      return;
    }
    const pick = (choice) => {
      popup.remove();
      onFocus(choice.key, choice.detour);
    };
    popup = new maplibregl.Popup({ maxWidth: "320px" })
      .setLngLat(event.lngLat)
      .setDOMContent(chooserContent(choices, routesByKey, loadDetail, pick))
      .addTo(map);
  });

  for (const layerId of [NETWORK_LAYER, DETOURED_LAYER, SKIPPED_LAYER, STARTS_LAYER]) {
    map.on("mouseenter", layerId, () => {
      map.getCanvas().style.cursor = "pointer";
    });
    map.on("mouseleave", layerId, () => {
      map.getCanvas().style.cursor = "";
    });
  }
}
