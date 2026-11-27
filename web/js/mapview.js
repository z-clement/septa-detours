// Everything that touches MapLibre: the map, its layers, popups.
// The only module that uses the global `maplibregl` (from the UMD script
// in index.html).

import { element, routeBadge } from "./dom.js";
import { choiceText, legendRows } from "./format.js";
import { clickChoices, detouredKeys, withRouteLabels } from "./routes.js";

const BASEMAP_STYLE = "https://tiles.openfreemap.org/styles/positron";

/** Used when a route's `color` is null (export emits null, never junk). */
const FALLBACK_COLOR = "#555555";

/** The faint whole-network lines (decided: one neutral grey, not route colors). */
const NETWORK_COLOR = "#9aa0a6";

/** Every detour mark (path, skipped stretch on the overview, start and
 * rejoin dots) in one accent color no SEPTA route uses (UI plan A1), so
 * detours stand out from routes. app.css repeats it (`--detour-color`). */
const DETOUR_COLOR = "#D500F9";

/** Detoured routes on the overview: grey like the network (A1), a little
 * darker and wider, so the affected routes still show. */
const DETOURED_ROUTE_COLOR = "#7d838a";

/** The skipped stretch on the overview, where routes are grey: a light
 * band of the accent. (Focused, it's a white fade over the route color.) */
const SKIPPED_OVERVIEW_OPACITY = 0.35;

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
const PATHS_SOURCE = "paths";
const REJOINS_SOURCE = "rejoins";
const MARKERS_SOURCE = "markers";
const FOCUS_SOURCE = "focus";
const NETWORK_LAYER = "network-lines";
const DETOURED_LAYER = "detoured-lines";
const FOCUS_LAYER = "focus-lines";
const FOCUS_ARROWS_LAYER = "focus-arrows";
const ARROW_IMAGE = "direction-arrow";
const PATH_ARROW_IMAGE = "path-arrow";
const PATH_ARROWS_LAYER = "path-arrows";
const SKIPPED_LAYER = "skipped-fade";
const PATH_CASING_LAYER = "path-casing";
const PATH_LAYER = "path-dashes";
const REJOIN_LAYER = "rejoin-dots";
const STARTS_LAYER = "start-dots";
const MARKER_LAYER = "detour-markers";
const MARKER_LABEL_LAYER = "detour-marker-labels";
const START_LABEL_LAYER = "start-dot-labels";

/** Zoomed out below this, each detour is a route-number marker; from it
 * up, its start dot, skipped stretch and path (UI plan B1). Check by eye. */
const MARKER_ZOOM = 13;

/** The basemap's own bold font (OpenFreeMap Positron serves Noto Sans):
 * MapLibre draws text with the style's glyphs only. */
const LABEL_FONT = ["Noto Sans Bold"];

/** Sources whose features are detours (`key` + `source_key`): their
 * hover/selected feature-state goes on both. */
const DETOUR_SOURCES = [STARTS_SOURCE, SKIPPED_SOURCE, PATHS_SOURCE, REJOINS_SOURCE];

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
    attributionControl: false,
  });
  map.addControl(new maplibregl.NavigationControl());
  // Compact: an (i) button that opens the credits, not a two-line box
  // across the bottom of a phone's map (render sweep finding 6). MapLibre
  // shows it open at first; close it once the map has loaded.
  const attribution = new maplibregl.AttributionControl({ compact: true });
  map.addControl(attribution);
  map.once("load", () => {
    map
      .getContainer()
      .querySelector(".maplibregl-ctrl-attrib")
      ?.classList.remove("maplibregl-compact-show");
  });
  return map;
}

/**
 * Draw the overview: the whole network faintly, detoured routes in color,
 * the stretch each detour in effect skips faded out, the streets it takes
 * instead dashed, and every placed detour's start point on top. Returns
 * the functions
 * that change it afterwards: `showFocus` (the overview or one focused
 * route) and the dot highlights `setHoveredDot` / `setSelectedDot`.
 *
 * Must run after the style has loaded (adding a source before then throws).
 * Layers draw in the order they're added: network, detoured, the focused
 * route (empty until one is focused), the fade over skipped stretches,
 * detour paths, the focused route's rejoin dots, start dots.
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
 * @param {{routes: object[], network: object, starts: object, skipped: object, paths: object}} site
 * @returns {{
 *   showFocus: (focus: {key: string, detail: object | null, rejoins: object | null} | null) => void,
 *   setInEffect: (keys: Set<string>) => void,
 *   setMarkers: (markers: object) => void,
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
    // `label`: each dot's route number, for the zoomed-out markers.
    data: withRouteLabels(site.starts, site.routes),
    promoteId: "source_key",
  });
  map.addSource(SKIPPED_SOURCE, {
    type: "geojson",
    data: site.skipped,
    promoteId: "source_key",
  });
  map.addSource(PATHS_SOURCE, {
    type: "geojson",
    data: site.paths,
    promoteId: "source_key",
  });
  map.addSource(FOCUS_SOURCE, { type: "geojson", data: EMPTY_COLLECTION });
  // The overview's markers (`routeMarkers`), set by `setMarkers`.
  map.addSource(MARKERS_SOURCE, { type: "geojson", data: EMPTY_COLLECTION });
  map.addSource(REJOINS_SOURCE, {
    type: "geojson",
    data: EMPTY_COLLECTION,
    promoteId: "source_key",
  });

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

  // The same lines again, only for detoured routes: grey and a little
  // darker on the overview (A1); in the route's own color while a focused
  // route's detail loads (`showFocus`).
  // `["literal", [...]]` marks the array as data, not an expression.
  const detouredFilter = ["in", ["get", "key"], ["literal", detouredKeys(site.routes)]];
  map.addLayer({
    id: DETOURED_LAYER,
    type: "line",
    source: NETWORK_SOURCE,
    filter: detouredFilter,
    layout: lineLayout,
    paint: {
      "line-color": DETOURED_ROUTE_COLOR,
      "line-width": ["interpolate", ["linear"], ["zoom"], 10, 1, 16, 3],
      "line-offset": offset,
    },
  });

  // The focused route's lines (route detail): each direction drawn once,
  // in pieces (U5b), as thick as detoured lines. Empty on the overview.
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
        2,
        16,
        6,
      ],
      "line-offset": offset,
    },
  });

  // Which way each of the focused route's lines runs (U5, your choice:
  // arrows, nothing faded): white chevrons along it, pointing the way
  // the bus goes (a shape's points run in travel order, and a line
  // symbol follows them). Shifted sideways like the lines (`icon-offset`
  // is in the icon's own frame: +y is right of travel), so each arrow
  // sits on its own direction's line. From zoom 13: thinner lines can't
  // hold them.
  addArrowImage(map, ARROW_IMAGE, null);
  addArrowImage(map, PATH_ARROW_IMAGE, DETOUR_COLOR);
  map.addLayer({
    id: FOCUS_ARROWS_LAYER,
    type: "symbol",
    source: FOCUS_SOURCE,
    minzoom: 13,
    layout: {
      "symbol-placement": "line",
      "symbol-spacing": 80,
      "icon-image": ARROW_IMAGE,
      "icon-rotation-alignment": "map",
      "icon-allow-overlap": true,
      "icon-ignore-placement": true,
      "icon-offset": [
        "interpolate",
        ["linear"],
        ["zoom"],
        13,
        ["literal", [0, 2.5]],
        16,
        ["literal", [0, 4]],
      ],
    },
  });

  // Hovered (a card under the pointer) or selected: bigger, and selected
  // gets a dark ring. `feature-state` is set per detour by the setters
  // below, on its dot, stretch and path alike (the fade doesn't use it).
  const hovered = ["boolean", ["feature-state", "hover"], false];
  const selected = ["boolean", ["feature-state", "selected"], false];
  const emphasized = ["any", hovered, selected];

  // The stretch of regular route each detour skips (tier B). On the
  // overview (routes grey): a light band of the accent. Focused (route in
  // its color): faded out, a semi-transparent white line over the route
  // (still drawn whole underneath). Either is a little wider than the
  // route so its edges show too (`showFocus` switches them). Butt caps,
  // so it ends exactly at the start and rejoin points. Same offset
  // as the route lines: a stretch is cut from its direction's shape, in
  // travel order, so it lands on that side.
  //
  // Detour layers (stretches, paths, start dots) show only detours in
  // effect: `setInEffect` sets which (nothing until it's first called).
  let inEffect = sourceKeyIn(new Set());
  map.addLayer({
    id: SKIPPED_LAYER,
    type: "line",
    source: SKIPPED_SOURCE,
    minzoom: MARKER_ZOOM,
    filter: inEffect,
    layout: { "line-cap": "butt", "line-join": "round" },
    paint: {
      "line-color": DETOUR_COLOR,
      "line-opacity": SKIPPED_OVERVIEW_OPACITY,
      "line-width": ["interpolate", ["linear"], ["zoom"], 10, 3, 16, 8],
      "line-offset": offset,
    },
  });

  // Where each detour in effect goes instead (tier C): accent dashes over
  // a white casing, so the gaps show white, unlike any solid route line. Wider when hovered or
  // selected. Same offset: a path's points run in travel order.
  const pathWidth = (narrow, wide) => [
    "interpolate",
    ["linear"],
    ["zoom"],
    10,
    ["case", emphasized, narrow * 1.5, narrow],
    16,
    ["case", emphasized, wide * 1.5, wide],
  ];
  map.addLayer({
    id: PATH_CASING_LAYER,
    type: "line",
    source: PATHS_SOURCE,
    minzoom: MARKER_ZOOM,
    filter: inEffect,
    layout: lineLayout,
    paint: {
      "line-color": "#ffffff",
      "line-width": pathWidth(3, 8),
      "line-offset": offset,
    },
  });
  map.addLayer({
    id: PATH_LAYER,
    type: "line",
    source: PATHS_SOURCE,
    minzoom: MARKER_ZOOM,
    filter: inEffect,
    // Dashes need butt caps: round caps would fill the gaps in.
    layout: { "line-cap": "butt", "line-join": "round" },
    paint: {
      "line-color": DETOUR_COLOR,
      "line-width": pathWidth(2, 5),
      // In line widths: dash 2, gap 1.5.
      "line-dasharray": [2, 1.5],
      "line-offset": offset,
    },
  });

  // Which way each detour path runs (yours, after U5b): the route's
  // chevrons, outlined in the accent so they show on the dashes and in
  // the white gaps between them. Like the paths: detours in effect, from
  // MARKER_ZOOM on the overview, every zoom when focused.
  map.addLayer({
    id: PATH_ARROWS_LAYER,
    type: "symbol",
    source: PATHS_SOURCE,
    minzoom: MARKER_ZOOM,
    filter: inEffect,
    layout: {
      "symbol-placement": "line",
      "symbol-spacing": 70,
      "icon-image": PATH_ARROW_IMAGE,
      "icon-rotation-alignment": "map",
      "icon-allow-overlap": true,
      "icon-ignore-placement": true,
      "icon-offset": [
        "interpolate",
        ["linear"],
        ["zoom"],
        13,
        ["literal", [0, 2.5]],
        16,
        ["literal", [0, 4]],
      ],
    },
  });

  // Where each of the focused route's detours in effect is back on route
  // (`rejoinCollection`; empty on the overview): a hollow accent ring,
  // smaller than a start dot (a solid accent dot), so start and end read
  // apart. Bigger when hovered or selected, like its start dot.
  map.addLayer({
    id: REJOIN_LAYER,
    type: "circle",
    source: REJOINS_SOURCE,
    paint: {
      "circle-color": "#ffffff",
      "circle-radius": [
        "interpolate",
        ["linear"],
        ["zoom"],
        10,
        ["case", emphasized, 5, 3],
        16,
        ["case", emphasized, 9, 6],
      ],
      "circle-stroke-color": DETOUR_COLOR,
      "circle-stroke-width": 2.5,
    },
  });

  // Start dots of detours in effect: solid accent, a white ring (dark
  // when selected).
  map.addLayer({
    id: STARTS_LAYER,
    type: "circle",
    source: STARTS_SOURCE,
    minzoom: MARKER_ZOOM,
    filter: inEffect,
    paint: {
      "circle-color": DETOUR_COLOR,
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
      "circle-stroke-color": ["case", selected, SELECTED_RING_COLOR, "#ffffff"],
      "circle-stroke-width": ["case", selected, 3, 2],
    },
  });

  // From MARKER_ZOOM on the overview: each start dot's route number beside
  // it (render sweep finding 4: near City Hall you couldn't tell whose
  // dot was whose). Hidden when focused: every dot is that route's.
  map.addLayer({
    id: START_LABEL_LAYER,
    type: "symbol",
    source: STARTS_SOURCE,
    minzoom: MARKER_ZOOM,
    filter: inEffect,
    layout: {
      "text-field": ["get", "label"],
      "text-font": LABEL_FONT,
      "text-size": 11,
      "text-anchor": "left",
      "text-offset": [0.9, 0],
      "text-allow-overlap": false,
    },
    paint: { "text-color": "#222222", "text-halo-color": "#ffffff", "text-halo-width": 1.5 },
  });

  // Zoomed out: an accent circle with the route number (B1) per route per
  // place (`routeMarkers`: a route's nearby detours share one), on top of
  // everything. Where different routes' markers crowd, MapLibre hides
  // labels that would overlap; every circle stays. Overview only (no
  // cards to hover); a click focuses the route with its first detour.
  map.addLayer({
    id: MARKER_LAYER,
    type: "circle",
    source: MARKERS_SOURCE,
    maxzoom: MARKER_ZOOM,
    paint: {
      "circle-color": DETOUR_COLOR,
      "circle-radius": 11,
      "circle-stroke-color": "#ffffff",
      "circle-stroke-width": 2,
    },
  });
  map.addLayer({
    id: MARKER_LABEL_LAYER,
    type: "symbol",
    source: MARKERS_SOURCE,
    maxzoom: MARKER_ZOOM,
    layout: {
      "text-field": ["get", "label"],
      "text-font": LABEL_FONT,
      "text-size": 11,
      "text-allow-overlap": false,
    },
    paint: { "text-color": "#ffffff" },
  });

  /**
   * Show the overview (`null`) or one focused route.
   *
   * Focused: the network fainter, other routes' colored lines and dots
   * hidden, the route's own dots kept, its rejoin dots shown
   * (`rejoins`, built from `detail`). Detour layers keep showing only
   * detours in effect. Its shapes come from `detail`;
   * while that's loading (null), its network lines stay in color so the
   * route doesn't vanish meanwhile. Focused, the detour layers show at
   * every zoom and the markers are off. Doesn't move the camera
   * (`fitDetours`, `fitRoute`).
   *
   * @param {{key: string, detail: object | null, rejoins: object | null} | null} focus
   *   `rejoins`: `rejoinCollection`'s, null while the detail loads
   */
  let only = null;
  /** Detour layers: in effect, and on the focused route if one is. */
  function applyDetourFilters() {
    const filter = only === null ? inEffect : ["all", only, inEffect];
    for (const layer of [
      STARTS_LAYER,
      START_LABEL_LAYER,
      SKIPPED_LAYER,
      PATH_CASING_LAYER,
      PATH_LAYER,
      PATH_ARROWS_LAYER,
    ]) {
      map.setFilter(layer, filter);
    }
  }

  function showFocus(focus) {
    only = focus === null ? null : ["==", ["get", "key"], focus.key];
    const detail = focus === null ? null : focus.detail;
    map.setPaintProperty(
      NETWORK_LAYER,
      "line-opacity",
      focus === null ? NETWORK_OPACITY : NETWORK_OPACITY_FOCUSED,
    );
    map.setFilter(DETOURED_LAYER, only ?? detouredFilter);
    map.setPaintProperty(
      DETOURED_LAYER,
      "line-color",
      focus === null ? DETOURED_ROUTE_COLOR : routeColor,
    );
    map.setPaintProperty(SKIPPED_LAYER, "line-color", focus === null ? DETOUR_COLOR : "#ffffff");
    map.setPaintProperty(
      SKIPPED_LAYER,
      "line-opacity",
      focus === null ? SKIPPED_OVERVIEW_OPACITY : SKIPPED_FADE_OPACITY,
    );
    map.setLayoutProperty(DETOURED_LAYER, "visibility", detail === null ? "visible" : "none");
    applyDetourFilters();
    // Focused, one route has nothing to untangle: its dots, stretches and
    // paths at every zoom, no markers. The overview: markers below
    // MARKER_ZOOM, the rest from it (B1).
    const detailed = focus === null ? MARKER_ZOOM : 0;
    for (const layer of [
      STARTS_LAYER,
      SKIPPED_LAYER,
      PATH_CASING_LAYER,
      PATH_LAYER,
      PATH_ARROWS_LAYER,
    ]) {
      map.setLayerZoomRange(layer, detailed, 24);
    }
    for (const layer of [MARKER_LAYER, MARKER_LABEL_LAYER, START_LABEL_LAYER]) {
      map.setLayoutProperty(layer, "visibility", focus === null ? "visible" : "none");
    }
    map.getSource(FOCUS_SOURCE).setData(detail === null ? EMPTY_COLLECTION : detail.shapes);
    map.getSource(REJOINS_SOURCE).setData(focus?.rejoins ?? EMPTY_COLLECTION);
  }

  /**
   * Which detours the map draws: those whose `source_key` is in `keys`
   * (`inEffectKeys`, recomputed by the caller as the clock moves).
   *
   * @param {Set<string>} keys
   */
  function setInEffect(keys) {
    inEffect = sourceKeyIn(keys);
    applyDetourFilters();
  }

  /**
   * The overview's markers, from `routeMarkers` (recomputed by the caller
   * as the clock moves, like `setInEffect`).
   *
   * @param {{type: string, features: object[]}} markers
   */
  function setMarkers(markers) {
    map.getSource(MARKERS_SOURCE).setData(markers);
  }

  return {
    showFocus,
    setInEffect,
    setMarkers,
    setHoveredDot: dotStateSetter(map, "hover"),
    setSelectedDot: dotStateSetter(map, "selected"),
  };
}

/**
 * Add a direction arrow: a white chevron pointing right (east), as line
 * symbols expect, drawn on a canvas at twice its size for sharp screens
 * (12 CSS px), outlined in `outline` when given (so it shows on white).
 *
 * @param {maplibregl.Map} map
 * @param {string} name the image's id
 * @param {string | null} outline a CSS color, or null for none
 */
function addArrowImage(map, name, outline) {
  const size = 24;
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const context = canvas.getContext("2d");
  context.lineCap = "round";
  context.lineJoin = "round";
  const chevron = (color, width) => {
    context.strokeStyle = color;
    context.lineWidth = width;
    context.beginPath();
    context.moveTo(9, 5);
    context.lineTo(16, 12);
    context.lineTo(9, 19);
    context.stroke();
  };
  if (outline !== null) {
    chevron(outline, 8);
  }
  chevron("#ffffff", 4);
  map.addImage(name, context.getImageData(0, 0, size, size), { pixelRatio: 2 });
}

/**
 * A filter keeping features whose `source_key` is in `keys`.
 *
 * @param {Set<string>} keys
 * @returns {Array} a MapLibre filter expression
 */
function sourceKeyIn(keys) {
  return ["in", ["get", "source_key"], ["literal", [...keys]]];
}

/**
 * A setter that puts feature-state `name` on one detour at a time: its
 * start dot, skipped stretch, path and rejoin dot (`DETOUR_SOURCES`).
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

/** The closest the camera zooms when framing detours: a short detour
 * (or one point) would otherwise fill the screen. */
const DETOUR_MAX_ZOOM = 16;

/**
 * Move the camera to some detours (animated), clear of the sheet, no
 * closer than `DETOUR_MAX_ZOOM` (UI plan C1).
 *
 * @param {maplibregl.Map} map
 * @param {[[number, number], [number, number]]} bounds from `detourBounds`
 * @param {number} [coverBottom] pixels hidden at the map's bottom
 */
export function fitDetours(map, bounds, coverBottom = 0) {
  map.fitBounds(bounds, { padding: fitPadding(coverBottom), maxZoom: DETOUR_MAX_ZOOM });
}

/**
 * The map key, top left (a MapLibre control, so the map places it on
 * every screen size): only rows for what the current view draws
 * (`legendRows`), redrawn as the map zooms and when a route is focused.
 * A `<details>`: its "Map key" summary opens and closes it; `open` says
 * how it starts (open on wide screens, closed on phones, where it would
 * cover much of the map).
 *
 * @param {maplibregl.Map} map
 * @param {{open: boolean}} options
 * @returns {{showLegendFor: (route: object | null) => void}}
 *   `showLegendFor`: the focused route's routes.json entry, or null
 */
export function addLegend(map, { open }) {
  const legend = element("details", "maplibregl-ctrl legend");
  legend.open = open;
  legend.append(element("summary", undefined, "Map key"));
  const rows = element("div", "legend-rows");
  legend.append(rows);
  let focused = null;
  const render = () => {
    const view = { focused: focused !== null, zoom: map.getZoom(), detailZoom: MARKER_ZOOM };
    rows.replaceChildren(
      ...legendRows(view).map(({ kind, text }) => {
        const item = element("div", "legend-row");
        const swatch = element("span", `legend-swatch legend-${kind}`);
        swatch.setAttribute("aria-hidden", "true");
        item.append(swatch, element("span", undefined, text));
        return item;
      }),
    );
    // The focused route's swatches take its color (app.css).
    legend.style.setProperty("--route-color", focused?.color ?? FALLBACK_COLOR);
  };
  // Only when the rows can change: crossing the zoom threshold.
  let detailed = null;
  map.on("zoom", () => {
    const now = map.getZoom() >= MARKER_ZOOM;
    if (now !== detailed) {
      detailed = now;
      render();
    }
  });
  render();
  map.addControl(
    {
      onAdd: () => legend,
      onRemove: () => legend.remove(),
    },
    "top-left",
  );
  return {
    showLegendFor(route) {
      focused = route;
      render();
    },
  };
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
    // A skipped stretch or a path is a detour too (key + source_key): it
    // counts as a dot, selecting its detour.
    const dots = map.queryRenderedFeatures(event.point, {
      layers: [MARKER_LAYER, STARTS_LAYER, REJOIN_LAYER, SKIPPED_LAYER, PATH_LAYER],
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

  for (const layerId of [
    NETWORK_LAYER,
    DETOURED_LAYER,
    SKIPPED_LAYER,
    PATH_LAYER,
    REJOIN_LAYER,
    STARTS_LAYER,
    MARKER_LAYER,
  ]) {
    map.on("mouseenter", layerId, () => {
      map.getCanvas().style.cursor = "pointer";
    });
    map.on("mouseleave", layerId, () => {
      map.getCanvas().style.cursor = "";
    });
  }
}
