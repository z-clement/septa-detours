// Everything that touches MapLibre: the map, its layers, popups.
// The only module that uses the global `maplibregl` (from the UMD script
// in index.html).

import { describeDetour, describeRoute } from "./format.js";
import { detouredKeys } from "./routes.js";

const BASEMAP_STYLE = "https://tiles.openfreemap.org/styles/positron";

/** Used when a route's `color` is null (export emits null, never junk). */
const FALLBACK_COLOR = "#555555";

/** The faint whole-network lines (decided: one neutral grey, not route colors). */
const NETWORK_COLOR = "#9aa0a6";

/** Start dots of detours that have ended. */
const ENDED_COLOR = "#9e9e9e";

/** Rough centre of Philadelphia, [lon, lat], shown before the data arrives. */
const PHILLY_CENTER = [-75.16, 39.95];

/** The network's opacity on the overview, and fainter while a route is focused. */
const NETWORK_OPACITY = 0.6;
const NETWORK_OPACITY_FOCUSED = 0.3;

const NETWORK_SOURCE = "network";
const STARTS_SOURCE = "starts";
const FOCUS_SOURCE = "focus";
const NETWORK_LAYER = "network-lines";
const DETOURED_LAYER = "detoured-lines";
const FOCUS_LAYER = "focus-lines";
const STARTS_LAYER = "start-dots";

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
 * and every placed detour's start point on top. Returns `showFocus`,
 * which switches between the overview and one focused route.
 *
 * Must run after the style has loaded (adding a source before then throws).
 * Layers draw in the order they're added: network, detoured, the focused
 * route (empty until one is focused), dots.
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
 * @param {{routes: object[], network: object, starts: object}} site
 * @returns {(focus: {key: string, detail: object | null} | null) => void}
 *   see `showFocus` below
 */
export function addOverviewLayers(map, site) {
  map.addSource(NETWORK_SOURCE, { type: "geojson", data: site.network });
  map.addSource(STARTS_SOURCE, { type: "geojson", data: site.starts });
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
      "circle-radius": ["interpolate", ["linear"], ["zoom"], 10, 4, 16, 9],
      "circle-stroke-color": ["match", ["get", "timing"], "upcoming", routeColor, "#ffffff"],
      "circle-stroke-width": 2,
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
  return function showFocus(focus) {
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
    map.getSource(FOCUS_SOURCE).setData(detail === null ? EMPTY_COLLECTION : detail.shapes);
  };
}

/**
 * Move the camera to a route's lines (animated). A route without shapes
 * (`bounds` null) leaves the camera where it is.
 *
 * @param {maplibregl.Map} map
 * @param {object} route a routes.json entry
 */
export function fitRoute(map, route) {
  if (route.bounds !== null) {
    map.fitBounds(route.bounds, { padding: 40 });
  }
}

/**
 * Popup text for the start dots under a click: each detour's details.
 *
 * Dots only carry `key` and `source_key`; the details are in the route's
 * detail file, fetched (once per route) with `loadDetail`.
 *
 * @param {object[]} features clicked start-dot features
 * @param {Map<string, object>} routesByKey routes.json by key
 * @param {(key: string) => Promise<object>} loadDetail
 * @returns {Promise<string[]>}
 */
async function describeDots(features, routesByKey, loadDetail) {
  return Promise.all(
    features.map(async ({ properties: { key, source_key: sourceKey } }) => {
      const detail = await loadDetail(key);
      const detour = detail.detours.find((d) => d.source_key === sourceKey);
      return detour === undefined
        ? `Detour ${sourceKey} is missing from data/routes/${key}.json`
        : describeDetour(detour, routesByKey.get(key));
    }),
  );
}

/**
 * Show a popup for whatever was clicked, and a pointer cursor on hover.
 *
 * One handler for the whole map instead of one per layer: a start dot
 * usually sits on its route line, and per-layer handlers would then open
 * two popups for one click. `queryRenderedFeatures` returns every drawn
 * feature under the click; dots win, and lines are listed only when no
 * dot was hit. Overlapping dots are all listed; for lines, each route
 * once (a route's directions and shapes overlap).
 *
 * @param {maplibregl.Map} map
 * @param {object[]} routes routes.json
 * @param {(key: string) => Promise<object>} loadDetail
 */
export function addPopups(map, routes, loadDetail) {
  const routesByKey = new Map(routes.map((route) => [route.key, route]));

  map.on("click", (event) => {
    const dots = map.queryRenderedFeatures(event.point, { layers: [STARTS_LAYER] });
    const lines =
      dots.length > 0
        ? []
        : map.queryRenderedFeatures(event.point, { layers: [DETOURED_LAYER, NETWORK_LAYER] });
    if (dots.length === 0 && lines.length === 0) {
      return;
    }

    const popup = new maplibregl.Popup({ maxWidth: "360px" })
      .setLngLat(event.lngLat)
      // setText, not setHTML: the text is treated as text, never markup.
      .setText(dots.length > 0 ? "Loading…" : "")
      .addTo(map);

    if (dots.length === 0) {
      const keys = [...new Set(lines.map((feature) => feature.properties.key))];
      popup.setText(keys.map((key) => describeRoute(routesByKey.get(key))).join("\n\n"));
      return;
    }
    describeDots(dots, routesByKey, loadDetail)
      .then((texts) => popup.setText(texts.join("\n\n----\n\n")))
      .catch((err) => popup.setText(err.message));
  });

  for (const layerId of [NETWORK_LAYER, DETOURED_LAYER, STARTS_LAYER]) {
    map.on("mouseenter", layerId, () => {
      map.getCanvas().style.cursor = "pointer";
    });
    map.on("mouseleave", layerId, () => {
      map.getCanvas().style.cursor = "";
    });
  }
}
