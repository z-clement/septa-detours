// Load the page's data files: the data contract written by `export site`
// (see export/contract.py).

/** The contract version this page reads; status.json and route files carry it. */
export const SCHEMA_VERSION = 2;

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
