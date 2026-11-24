// Map page: draw one route's GeoJSON (written by `python -m septa_detours.export`)
// on a keyless OpenFreeMap basemap.

const DATA_URL = "data/bus-21.geojson";
const BASEMAP_STYLE = "https://tiles.openfreemap.org/styles/positron";

/** Used when a feature's `route_color` is null (export emits null, never junk). */
const FALLBACK_COLOR = "#555555";

/** Rough centre of Philadelphia, [lon, lat], shown before the data arrives. */
const PHILLY_CENTER = [-75.16, 39.95];

const SOURCE_ID = "route";
const LAYER_ID = "route-lines";

/**
 * Fetch and parse a GeoJSON FeatureCollection.
 *
 * `fetch` only rejects on network failure. A 404 (file not exported yet)
 * resolves normally with `response.ok === false`, so that is checked here
 * and turned into an Error naming the URL and status.
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
        "Export it first: uv run python -m septa_detours.export bus 21",
    );
  }
  return response.json(); // also a Promise; the caller's `await` unwraps it
}

/**
 * Bounding box of every LineString coordinate in the collection.
 *
 * Returned in the shape `map.fitBounds` accepts: [[west, south], [east, north]].
 * Coordinates are [lon, lat], so lon is x (west/east) and lat is y.
 *
 * @param {object} collection a FeatureCollection of LineStrings
 * @returns {[[number, number], [number, number]] | null} null when there
 *   are no coordinates at all (an empty collection has no bounds)
 */
function collectionBounds(collection) {
  let west = Infinity;
  let south = Infinity;
  let east = -Infinity;
  let north = -Infinity;

  for (const feature of collection.features) {
    // Destructuring: unpacks [lon, lat] like Python's `for lon, lat in ...`.
    for (const [lon, lat] of feature.geometry.coordinates) {
      west = Math.min(west, lon);
      east = Math.max(east, lon);
      south = Math.min(south, lat);
      north = Math.max(north, lat);
    }
  }

  // Still Infinity means the loop never saw a coordinate.
  if (west === Infinity) {
    return null;
  }
  return [
    [west, south],
    [east, north],
  ];
}

/**
 * Add the route as a GeoJSON source plus one line layer.
 *
 * Must run after the style has loaded (adding a source before then throws).
 *
 * Color: a MapLibre *expression*, i.e. a small program written as JSON
 * arrays and evaluated per feature on the GPU side. `["get", "route_color"]`
 * reads the property; `coalesce` takes the first non-null value, so a null
 * color falls back to FALLBACK_COLOR.
 *
 * Directions: `line-offset` shifts a line sideways relative to the order its
 * vertices are drawn in (positive = to the right of travel). Our two
 * directions are drawn in opposite orders, so the *same* positive offset puts
 * each one on its own side of the street (US right-hand traffic, like the
 * real buses), and they stop hiding each other.
 *
 * Known gap: a shape used by both directions gives two features with
 * identical geometry *and* vertex order, so the offset can't separate them;
 * they draw on top of each other. The click popup still lists both.
 *
 * @param {maplibregl.Map} map
 * @param {object} collection
 */
function addRouteLayers(map, collection) {
  map.addSource(SOURCE_ID, { type: "geojson", data: collection });

  map.addLayer({
    id: LAYER_ID,
    type: "line",
    source: SOURCE_ID,
    layout: {
      "line-cap": "round",
      "line-join": "round",
    },
    paint: {
      "line-color": ["coalesce", ["get", "route_color"], FALLBACK_COLOR],
      // `interpolate` over `zoom`: thin and close together when zoomed out,
      // wider and further apart when zoomed in (pairs are zoom, value).
      "line-width": ["interpolate", ["linear"], ["zoom"], 10, 1.5, 16, 5],
      "line-offset": ["interpolate", ["linear"], ["zoom"], 10, 1, 16, 4],
    },
  });
}

/**
 * Show a popup describing the clicked line(s), and a pointer cursor on hover.
 *
 * Useful for checking direction and shape_id against the data while
 * developing. Lists every feature under the click, so overlapping lines
 * (e.g. a shape shared by both directions) all show up.
 *
 * @param {maplibregl.Map} map
 */
function addRoutePopup(map) {
  // Passing a layer id as the second argument limits the event to that layer.
  map.on("click", LAYER_ID, (event) => {
    const lines = event.features.map((feature) => {
      const p = feature.properties;
      return `${p.route_short_name} ${p.route_long_name}\n` +
        `direction ${p.direction_id}, shape ${p.shape_id}`;
    });

    new maplibregl.Popup()
      .setLngLat(event.lngLat)
      // setText, not setHTML: the text is treated as text, never markup.
      .setText(lines.join("\n\n"))
      .addTo(map);
  });

  map.on("mouseenter", LAYER_ID, () => {
    map.getCanvas().style.cursor = "pointer";
  });
  map.on("mouseleave", LAYER_ID, () => {
    map.getCanvas().style.cursor = "";
  });
}

/**
 * Show an error message on the page (and in the console).
 *
 * @param {string} message
 */
function showError(message) {
  console.error(message);
  // textContent (not innerHTML) so the message can't inject markup.
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

  addRouteLayers(map, collection);
  addRoutePopup(map);

  const bounds = collectionBounds(collection);
  if (bounds === null) {
    showError(`${DATA_URL} has no route lines to show.`);
    return;
  }
  map.fitBounds(bounds, { padding: 40, duration: 0 });
}

// An async function returns a Promise; an error thrown inside it becomes a
// rejection, which `.catch` turns into a visible message instead of a
// silent console-only failure.
main().catch((err) => showError(err.message));
