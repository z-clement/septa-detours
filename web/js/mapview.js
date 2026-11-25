// Everything that touches MapLibre: the map, its layers, popups, bounds.
// The only module that uses the global `maplibregl` (from the UMD script
// in index.html).

import { describeLine, describeStart } from "./format.js";

const BASEMAP_STYLE = "https://tiles.openfreemap.org/styles/positron";

/** Used when a feature's `route_color` is null (export emits null, never junk). */
const FALLBACK_COLOR = "#555555";

/** Rough centre of Philadelphia, [lon, lat], shown before the data arrives. */
const PHILLY_CENTER = [-75.16, 39.95];

const SOURCE_ID = "detours";
const LINES_LAYER_ID = "detour-lines";
const STARTS_LAYER_ID = "detour-starts";

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
export function collectionBounds(collection) {
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
export function addDetourLayers(map, collection) {
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
export function addPopups(map) {
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

