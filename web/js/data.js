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

// --- The data contract (written by `export site`; see export/contract.py) ---

/** The contract version this page reads; status.json and route files carry it. */
export const SCHEMA_VERSION = 1;

/** The commands that make the contract's files, named when one is missing. */
const MAKE_SITE_COMMANDS =
  "uv run python -m septa_detours.match\n" +
  "uv run python -m septa_detours.export site";

/**
 * Fetch and parse one JSON file; a missing file names the commands.
 *
 * @param {string} url
 * @returns {Promise<any>}
 */
async function loadJson(url) {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(
      `Could not load ${url} (HTTP ${response.status}).\n` +
        `Make it first:\n${MAKE_SITE_COMMANDS}`,
    );
  }
  return response.json();
}

/**
 * Refuse a file written for another contract version: a stale page or
 * stale data, which would otherwise draw a silently broken map.
 *
 * @param {string} url
 * @param {object} file a parsed status.json or route detail file
 */
function checkSchema(url, file) {
  if (file.schema_version !== SCHEMA_VERSION) {
    throw new Error(
      `${url} has schema_version ${file.schema_version}; this page reads ` +
        `${SCHEMA_VERSION}.\nRe-export the data (or reload the page):\n` +
        "uv run python -m septa_detours.export site",
    );
  }
}

/**
 * Load everything the overview needs.
 *
 * status.json comes first, alone: if its schema_version is wrong, the
 * other files (network.geojson is ~1 MB) aren't downloaded at all. Then
 * the rest in parallel.
 *
 * @returns {Promise<{status: object, routes: object[], network: object, starts: object}>}
 */
export async function loadSite() {
  const status = await loadJson("data/status.json");
  checkSchema("data/status.json", status);
  const [routes, network, starts] = await Promise.all([
    loadJson("data/routes.json"),
    loadJson("data/network.geojson"),
    loadJson("data/starts.geojson"),
  ]);
  return { status, routes, network, starts };
}

/**
 * Make a loader for route detail files (routes/<key>.json), with a cache.
 *
 * Each file is fetched at most once: the cache holds the Promise, so two
 * calls while the first is still loading share one request. A failed load
 * is dropped from the cache, so asking again retries.
 *
 * @returns {(key: string) => Promise<object>}
 */
export function routeDetailLoader() {
  const cache = new Map();
  return (key) => {
    if (!cache.has(key)) {
      const url = `data/routes/${key}.json`;
      const promise = loadJson(url).then((detail) => {
        checkSchema(url, detail);
        return detail;
      });
      promise.catch(() => cache.delete(key));
      cache.set(key, promise);
    }
    return cache.get(key);
  };
}
