// Load the page's data files: the data contract written by `export site`
// (see export/contract.py).

/** The contract version this page reads; status.json and route files carry it. */
export const SCHEMA_VERSION = 10;

/** The commands that make the contract's files, named when one is missing. */
const MAKE_SITE_COMMANDS =
  "uv run python -m septa_detours.match\n" +
  "uv run python -m septa_detours.export site";

/**
 * A data file the page refused, with why: `reason` is "missing" (an HTTP
 * error) or "schema" (another contract version). The message is for
 * developers (the console); format.js `loadErrorText` writes the rider's.
 */
export class DataError extends Error {
  /**
   * @param {string} message
   * @param {"missing" | "schema"} reason
   */
  constructor(message, reason) {
    super(message);
    this.name = "DataError";
    this.reason = reason;
  }
}

/**
 * One export's URL for a data file: `path?v=<version>`.
 *
 * Every export has its own `generated_at`, so its files get URLs no
 * earlier export used. A browser (or GitHub Pages' fixed 10-minute cache)
 * can then keep them as long as it likes: a stale copy can't be served
 * for a new export, and a page never mixes files from two exports.
 *
 * @param {string} path e.g. "data/routes.json"
 * @param {string} version status.json's `generated_at`
 * @returns {string}
 */
export function versioned(path, version) {
  return `${path}?v=${encodeURIComponent(version)}`;
}

/**
 * Fetch and parse one JSON file; a missing file's message names the
 * commands that make it.
 *
 * `fresh`: ask the server before using a cached copy (`cache: "no-cache"`;
 * a cheap 304 when unchanged). Only status.json needs it: it's the one
 * file whose URL never changes, and it names the version of the rest.
 * (Seen before versioned URLs: `python -m http.server` sends no
 * Cache-Control, and the browser reused an old route file after a schema
 * bump; even Ctrl+Shift+R didn't clear it.)
 *
 * @param {string} url
 * @param {{fresh?: boolean}} [options]
 * @returns {Promise<any>}
 */
async function loadJson(url, { fresh = false } = {}) {
  const response = await (fresh ? fetch(url, { cache: "no-cache" }) : fetch(url));
  if (!response.ok) {
    throw new DataError(
      `Could not load ${url} (HTTP ${response.status}).\n` +
        `Make it first:\n${MAKE_SITE_COMMANDS}`,
      "missing",
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
    throw new DataError(
      `${url} has schema_version ${file.schema_version}; this page reads ` +
        `${SCHEMA_VERSION}.\nRe-export the data (or reload the page):\n` +
        "uv run python -m septa_detours.export site",
      "schema",
    );
  }
}

/**
 * Load everything the overview needs.
 *
 * status.json comes first, alone and fresh: if its schema_version is
 * wrong, the other files (network.geojson is ~1 MB) aren't downloaded at
 * all. Then the rest in parallel, at the export's versioned URLs.
 *
 * @returns {Promise<{status: object, routes: object[], network: object, starts: object, skipped: object, paths: object}>}
 */
export async function loadSite() {
  const status = await loadJson("data/status.json", { fresh: true });
  checkSchema("data/status.json", status);
  const load = (path) => loadJson(versioned(path, status.generated_at));
  const [routes, network, starts, skipped, paths] = await Promise.all([
    load("data/routes.json"),
    load("data/network.geojson"),
    load("data/starts.geojson"),
    load("data/skipped.geojson"),
    load("data/paths.geojson"),
  ]);
  return { status, routes, network, starts, skipped, paths };
}

/**
 * The `generated_at` of the export on the server now (status.json, asked
 * fresh), for an open page's check for newer detours (main.js).
 *
 * @returns {Promise<string>}
 */
export async function latestVersion() {
  return (await loadJson("data/status.json", { fresh: true })).generated_at;
}

/**
 * Whether `latest` is a later export than `current` (two `generated_at`s).
 *
 * Later, not merely different: a server or cache still holding an older
 * status.json mustn't offer a reload to older data. Either one
 * unparseable gives false (`NaN` compares false).
 *
 * @param {string} current the page's export
 * @param {string} latest the server's, from `latestVersion`
 * @returns {boolean}
 */
export function isNewerExport(current, latest) {
  return Date.parse(latest) > Date.parse(current);
}

/**
 * Make a loader for route detail files (routes/<key>.json), with a cache.
 *
 * Each file is fetched at most once: the cache holds the Promise, so two
 * calls while the first is still loading share one request. A failed load
 * is dropped from the cache, so asking again retries.
 *
 * @param {string} version status.json's `generated_at` (see `versioned`)
 * @returns {(key: string) => Promise<object>}
 */
export function routeDetailLoader(version) {
  const cache = new Map();
  return (key) => {
    if (!cache.has(key)) {
      const url = versioned(`data/routes/${key}.json`, version);
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
