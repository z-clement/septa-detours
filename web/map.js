// Map page: draw the detours GeoJSON (written by
// `python -m septa_detours.export detours`) on a keyless OpenFreeMap basemap.
//
// The file is one FeatureCollection with two kinds of feature:
//   - LineString: a detoured route's shape (one per route/shape/direction),
//     with route properties, shape_id, direction_id and detour_count.
//   - Point: where a detour starts, with route properties plus the
//     detour's own fields (location_start, start, end, message, ...).

import { describeLine, describeStart, summarize } from "./js/format.js";

const DATA_URL = "data/detours.geojson";
const BASEMAP_STYLE = "https://tiles.openfreemap.org/styles/positron";

/** The commands that make DATA_URL, named when it's missing. */
const MAKE_DATA_COMMANDS =
  "uv run python -m septa_detours.match\n" +
  "uv run python -m septa_detours.export detours";

/** Used when a feature's `route_color` is null (export emits null, never junk). */
const FALLBACK_COLOR = "#555555";

/** Rough centre of Philadelphia, [lon, lat], shown before the data arrives. */
const PHILLY_CENTER = [-75.16, 39.95];

const SOURCE_ID = "detours";
const LINES_LAYER_ID = "detour-lines";
const STARTS_LAYER_ID = "detour-starts";

/**
 * Fetch and parse a GeoJSON FeatureCollection.
 *
 * `fetch` only rejects on network failure. A 404 (file not exported yet)
 * resolves normally with `response.ok === false`, so that is checked here
 * and turned into an Error naming the URL, the status, and the commands
 * that make the file.
 *
 * @param {string} url
 * @returns {Promise<object>} the parsed FeatureCollection
 */
async function loadCollection(url) {
  const response = await fetch(url);
  if (!response.ok) {
    // Template literal: backticks with ${...} interpolate, like a Python f-string.
    throw new Error(
      `Could not load ${url} (HTTP ${response.status}).\n` +
        `Make it first:\n${MAKE_DATA_COMMANDS}`,
    );
  }
  return response.json(); // also a Promise; the caller's `await` unwraps it
}

/**
 * Every [lon, lat] position of one feature, whatever its geometry type.
 *
 * A Point's `coordinates` is a single position; a LineString's is a list of
 * them. Returning a list either way lets callers loop without caring.
 *
 * @param {object} feature
 * @returns {Array<[number, number]>}
 */
function featurePositions(feature) {
  const { type, coordinates } = feature.geometry;
  return type === "Point" ? [coordinates] : coordinates;
}

/**
 * Bounding box of every position in the collection, lines and points.
 *
 * Returned in the shape `map.fitBounds` accepts: [[west, south], [east, north]].
 * Coordinates are [lon, lat], so lon is x (west/east) and lat is y.
 *
 * @param {object} collection a FeatureCollection
 * @returns {[[number, number], [number, number]] | null} null when there
 *   are no positions at all (an empty collection has no bounds)
 */
function collectionBounds(collection) {
  let west = Infinity;
  let south = Infinity;
  let east = -Infinity;
  let north = -Infinity;

  for (const feature of collection.features) {
    // Destructuring: unpacks [lon, lat] like Python's `for lon, lat in ...`.
    for (const [lon, lat] of featurePositions(feature)) {
      west = Math.min(west, lon);
      east = Math.max(east, lon);
      south = Math.min(south, lat);
      north = Math.max(north, lat);
    }
  }

  // Still Infinity means the loop never saw a position.
  if (west === Infinity) {
    return null;
  }
  return [
    [west, south],
    [east, north],
  ];
}

/**
 * Add the collection as one GeoJSON source and two layers on top of it.
 *
 * Must run after the style has loaded (adding a source before then throws).
 *
 * Each layer has a `filter`: an expression that must be true for a feature
 * to be drawn by that layer. `["geometry-type"]` is the feature's type, so
 * the line layer only sees LineStrings and the circle layer only Points.
 * Layers draw in the order they're added, so the circles end up on top.
 *
 * Color: a MapLibre *expression*, i.e. a small program written as JSON
 * arrays and evaluated per feature on the GPU side. `["get", "route_color"]`
 * reads the property; `coalesce` takes the first non-null value, so a null
 * color falls back to FALLBACK_COLOR.
 *
 * Directions: `line-offset` shifts a line sideways relative to the order its
 * vertices are drawn in (positive = to the right of travel). A route's two
 * directions are drawn in opposite orders, so the *same* positive offset
 * puts each one on its own side of the street (US right-hand traffic, like
 * the real buses), and they stop hiding each other.
 *
 * Known gap: a shape used by both directions gives two features with
 * identical geometry *and* vertex order, so the offset can't separate them;
 * they draw on top of each other. The click popup still lists both.
 *
 * @param {maplibregl.Map} map
 * @param {object} collection
 */
function addDetourLayers(map, collection) {
  map.addSource(SOURCE_ID, { type: "geojson", data: collection });

  const routeColor = ["coalesce", ["get", "route_color"], FALLBACK_COLOR];

  map.addLayer({
    id: LINES_LAYER_ID,
    type: "line",
    source: SOURCE_ID,
    filter: ["==", ["geometry-type"], "LineString"],
    layout: {
      "line-cap": "round",
      "line-join": "round",
    },
    paint: {
      "line-color": routeColor,
      // `interpolate` over `zoom`: thin and close together when zoomed out,
      // wider and further apart when zoomed in (pairs are zoom, value).
      "line-width": ["interpolate", ["linear"], ["zoom"], 10, 1.5, 16, 5],
      "line-offset": ["interpolate", ["linear"], ["zoom"], 10, 1, 16, 4],
    },
  });

  map.addLayer({
    id: STARTS_LAYER_ID,
    type: "circle",
    source: SOURCE_ID,
    filter: ["==", ["geometry-type"], "Point"],
    paint: {
      // Filled with the route's color; the white outline keeps a dot
      // visible on top of its own (same-colored) route line.
      "circle-color": routeColor,
      "circle-radius": ["interpolate", ["linear"], ["zoom"], 10, 4, 16, 9],
      "circle-stroke-color": "#ffffff",
      "circle-stroke-width": 2,
    },
  });
}

/**
 * Show a popup for whatever was clicked, and a pointer cursor on hover.
 *
 * One handler for the whole map instead of one per layer: a start point
 * usually sits on its route line, and per-layer handlers would then open
 * two popups for one click. `queryRenderedFeatures` returns every drawn
 * feature under the click; start points win, and lines are listed only
 * when no start point was hit. Every feature is listed, so overlapping
 * ones (several detours at one corner, a shape in both directions) all
 * show up.
 *
 * @param {maplibregl.Map} map
 */
function addPopups(map) {
  map.on("click", (event) => {
    const starts = map.queryRenderedFeatures(event.point, {
      layers: [STARTS_LAYER_ID],
    });
    const features =
      starts.length > 0
        ? starts
        : map.queryRenderedFeatures(event.point, { layers: [LINES_LAYER_ID] });
    if (features.length === 0) {
      return;
    }

    const texts = features.map((feature) =>
      feature.layer.id === STARTS_LAYER_ID
        ? describeStart(feature.properties)
        : describeLine(feature.properties),
    );

    new maplibregl.Popup({ maxWidth: "360px" })
      .setLngLat(event.lngLat)
      // setText, not setHTML: the text is treated as text, never markup.
      .setText(texts.join("\n\n----\n\n"))
      .addTo(map);
  });

  for (const layerId of [LINES_LAYER_ID, STARTS_LAYER_ID]) {
    map.on("mouseenter", layerId, () => {
      map.getCanvas().style.cursor = "pointer";
    });
    map.on("mouseleave", layerId, () => {
      map.getCanvas().style.cursor = "";
    });
  }
}

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

/** Build the map, load the data, draw it, and zoom to it. */
async function main() {
  const map = new maplibregl.Map({
    container: "map", // the id of the <div>
    style: BASEMAP_STYLE,
    center: PHILLY_CENTER,
    zoom: 11,
  });
  map.addControl(new maplibregl.NavigationControl());

  // The style loading and our data download are independent, so start both
  // and wait for both. `map.once("load")` with no callback returns a Promise.
  // Promise.all resolves to an array of results, in the order given; the
  // `[, collection]` skips the first (the load event, which we don't need).
  const [, collection] = await Promise.all([
    map.once("load"),
    loadCollection(DATA_URL),
  ]);

  addDetourLayers(map, collection);
  addPopups(map);
  showStatus(summarize(collection));

  // No bounds means no detours: a true state, not an error. The map stays
  // on Philadelphia and the status line says so.
  const bounds = collectionBounds(collection);
  if (bounds !== null) {
    map.fitBounds(bounds, { padding: 40, duration: 0 });
  }
}

// An async function returns a Promise; an error thrown inside it becomes a
// rejection, which `.catch` turns into a visible message instead of a
// silent console-only failure.
main().catch((err) => showError(err.message));
