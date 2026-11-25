// Load the page's data files.

const DATA_URL = "data/detours.geojson";

/** The commands that make DATA_URL, named when it's missing. */
const MAKE_DATA_COMMANDS =
  "uv run python -m septa_detours.match\n" +
  "uv run python -m septa_detours.export detours";

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
export async function loadCollection(url) {
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

/** Load the detours FeatureCollection the map draws. */
export function loadDetours() {
  return loadCollection(DATA_URL);
}
