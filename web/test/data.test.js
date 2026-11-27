// Tests for web/js/data.js's contract loaders. Run: node --test web/test/*.test.js
//
// `fetch` is replaced by a fake that serves files from a dictionary and
// records every URL asked for, in order, and every request's options.

import assert from "node:assert/strict";
import { beforeEach, test } from "node:test";

import {
  DataError,
  SCHEMA_VERSION,
  isNewerExport,
  latestVersion,
  loadSite,
  routeDetailLoader,
  versioned,
} from "../js/data.js";

let requested;
let options;

/** Serve `files` (url -> parsed JSON); anything else is a 404. */
function serve(files) {
  requested = [];
  options = [];
  globalThis.fetch = async (url, init) => {
    requested.push(url);
    options.push(init);
    if (!(url in files)) {
      return { ok: false, status: 404 };
    }
    return { ok: true, status: 200, json: async () => structuredClone(files[url]) };
  };
}

const GENERATED_AT = "2026-11-27T13:44:40Z"; // real (export site, snapshot 134432Z)
const V = "?v=2026-11-27T13%3A44%3A40Z";
const STATUS = {
  schema_version: 10,
  generated_at: GENERATED_AT,
  snapshot: "2026-11-27T134432Z.json",
};
const ROUTES = [{ key: "bus-2" }, { key: "rail-AIR" }];
const NETWORK = { type: "FeatureCollection", features: [{ id: "network" }] };
const STARTS = { type: "FeatureCollection", features: [{ id: "starts" }] };
const SKIPPED = { type: "FeatureCollection", features: [{ id: "skipped" }] };
const PATHS = { type: "FeatureCollection", features: [{ id: "paths" }] };
const SITE = {
  "data/status.json": STATUS,
  [`data/routes.json${V}`]: ROUTES,
  [`data/network.geojson${V}`]: NETWORK,
  [`data/starts.geojson${V}`]: STARTS,
  [`data/skipped.geojson${V}`]: SKIPPED,
  [`data/paths.geojson${V}`]: PATHS,
};
const SITE_FILE_COUNT = Object.keys(SITE).length;
const BUS_2 = { schema_version: 10, key: "bus-2", detours: [] };
const RAIL_AIR = { schema_version: 10, key: "rail-AIR", detours: [] };

beforeEach(() => serve({}));

test("SCHEMA_VERSION matches the Python contract's", () => {
  assert.equal(SCHEMA_VERSION, 10);
});

test("DataError: an Error with a name and a reason", () => {
  const err = new DataError("details", "missing");
  assert.ok(err instanceof Error);
  assert.deepEqual([err.name, err.message, err.reason], ["DataError", "details", "missing"]);
});

// --- versioned ------------------------------------------------------------

test("versioned: the export's generated_at as a query", () => {
  assert.equal(versioned("data/routes.json", GENERATED_AT), `data/routes.json${V}`);
});

test("versioned: a version that would break the URL is encoded", () => {
  // Hand-built: "+" reads as a space in a query, "#" starts a fragment.
  assert.equal(
    versioned("data/routes.json", "2026-11-27T13:44:40+00:00#x"),
    "data/routes.json?v=2026-11-27T13%3A44%3A40%2B00%3A00%23x",
  );
});

// --- loadSite ---------------------------------------------------------------

test("only status.json revalidates; versioned files use the normal cache", async () => {
  serve({ ...SITE, [`data/routes/bus-2.json${V}`]: BUS_2 });
  await loadSite();
  await routeDetailLoader(GENERATED_AT)("bus-2");
  assert.equal(options.length, SITE_FILE_COUNT + 1);
  assert.deepEqual(options, [{ cache: "no-cache" }, ...Array(SITE_FILE_COUNT).fill(undefined)]);
});

test("loadSite: returns every overview file, status first", async () => {
  serve(SITE);
  assert.deepEqual(await loadSite(), {
    status: STATUS,
    routes: ROUTES,
    network: NETWORK,
    starts: STARTS,
    skipped: SKIPPED,
    paths: PATHS,
  });
  assert.deepEqual(requested, [
    "data/status.json",
    `data/routes.json${V}`,
    `data/network.geojson${V}`,
    `data/starts.geojson${V}`,
    `data/skipped.geojson${V}`,
    `data/paths.geojson${V}`,
  ]);
});

test("loadSite: stale data (an older schema_version) fails before the other files", async () => {
  serve({ ...SITE, "data/status.json": { ...STATUS, schema_version: 9 } });
  await assert.rejects(loadSite(), {
    name: "DataError",
    reason: "schema",
    message:
      "data/status.json has schema_version 9; this page reads 10.\n" +
      "Re-export the data (or reload the page):\n" +
      "uv run python -m septa_detours.export site",
  });
  assert.deepEqual(requested, ["data/status.json"]);
});

test("loadSite: a status.json without schema_version is refused", async () => {
  const { schema_version: _, ...noVersion } = STATUS;
  serve({ ...SITE, "data/status.json": noVersion });
  await assert.rejects(loadSite(), /has schema_version undefined; this page reads 10/);
});

test("loadSite: a missing file names the URL, the status and the commands", async () => {
  const { [`data/network.geojson${V}`]: _, ...withoutNetwork } = SITE;
  serve(withoutNetwork);
  await assert.rejects(loadSite(), {
    name: "DataError",
    reason: "missing",
    message:
      `Could not load data/network.geojson${V} (HTTP 404).\nMake it first:\n` +
      "uv run python -m septa_detours.match\n" +
      "uv run python -m septa_detours.export site",
  });
});

test("loadSite: a missing status.json stops everything", async () => {
  serve({});
  await assert.rejects(loadSite(), /Could not load data\/status\.json \(HTTP 404\)/);
  assert.deepEqual(requested, ["data/status.json"]);
});

// --- latestVersion, isNewerExport -------------------------------------------

test("latestVersion: status.json's generated_at, asked fresh", async () => {
  const later = { ...STATUS, generated_at: "2026-11-27T14:00:12Z" };
  serve({ "data/status.json": later });
  assert.equal(await latestVersion(), "2026-11-27T14:00:12Z");
  assert.deepEqual(requested, ["data/status.json"]);
  assert.deepEqual(options, [{ cache: "no-cache" }]);
});

test("latestVersion: a missing status.json rejects", async () => {
  serve({});
  await assert.rejects(latestVersion(), { reason: "missing" });
});

test("isNewerExport: only a later export", () => {
  assert.equal(isNewerExport(GENERATED_AT, "2026-11-27T14:00:12Z"), true);
  assert.equal(isNewerExport(GENERATED_AT, GENERATED_AT), false);
  // An older status.json (a cache or server behind the page) isn't newer.
  assert.equal(isNewerExport(GENERATED_AT, "2026-11-27T13:29:51Z"), false);
  // By time, not by text: the same instant written with an offset.
  assert.equal(isNewerExport(GENERATED_AT, "2026-11-27T08:44:40-05:00"), false);
  assert.equal(isNewerExport(GENERATED_AT, "2026-11-27T08:44:41-05:00"), true);
});

test("isNewerExport: anything unreadable is not newer", () => {
  assert.equal(isNewerExport(GENERATED_AT, undefined), false);
  assert.equal(isNewerExport(GENERATED_AT, "soon"), false);
  assert.equal(isNewerExport(undefined, GENERATED_AT), false);
});

// --- routeDetailLoader --------------------------------------------------------

test("routeDetailLoader: loads a route's file", async () => {
  serve({ [`data/routes/bus-2.json${V}`]: BUS_2 });
  const load = routeDetailLoader(GENERATED_AT);
  assert.deepEqual(await load("bus-2"), BUS_2);
  assert.deepEqual(requested, [`data/routes/bus-2.json${V}`]);
});

test("routeDetailLoader: each file is fetched once, even while loading", async () => {
  serve({ [`data/routes/bus-2.json${V}`]: BUS_2, [`data/routes/rail-AIR.json${V}`]: RAIL_AIR });
  const load = routeDetailLoader(GENERATED_AT);
  const first = load("bus-2");
  const second = load("bus-2"); // before the first has finished
  assert.equal(first, second);
  await first;
  await load("bus-2");
  assert.deepEqual(await load("rail-AIR"), RAIL_AIR);
  assert.deepEqual(requested, [`data/routes/bus-2.json${V}`, `data/routes/rail-AIR.json${V}`]);
});

test("routeDetailLoader: separate loaders have separate caches", async () => {
  serve({ [`data/routes/bus-2.json${V}`]: BUS_2 });
  await routeDetailLoader(GENERATED_AT)("bus-2");
  await routeDetailLoader(GENERATED_AT)("bus-2");
  assert.equal(requested.length, 2);
});

test("routeDetailLoader: a failed load is retried next time", async () => {
  serve({});
  const load = routeDetailLoader(GENERATED_AT);
  await assert.rejects(load("bus-2"), { reason: "missing" });
  await assert.rejects(load("bus-2"), /Could not load data\/routes\/bus-2\.json\?v=2026-11-27T13%3A44%3A40Z \(HTTP 404\)/);
  serve({ [`data/routes/bus-2.json${V}`]: BUS_2 });
  assert.deepEqual(await load("bus-2"), BUS_2);
});

test("routeDetailLoader: a newer route file (stale page) is refused, then retried", async () => {
  serve({ [`data/routes/bus-2.json${V}`]: { ...BUS_2, schema_version: 11 } });
  const load = routeDetailLoader(GENERATED_AT);
  await assert.rejects(
    load("bus-2"),
    /data\/routes\/bus-2\.json\?v=\S+ has schema_version 11; this page reads 10/,
  );
  await assert.rejects(load("bus-2"), { reason: "schema" });
  serve({ [`data/routes/bus-2.json${V}`]: BUS_2 });
  assert.deepEqual(await load("bus-2"), BUS_2);
});
