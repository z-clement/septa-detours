// Tests for web/js/data.js's contract loaders. Run: node --test web/test/
//
// `fetch` is replaced by a fake that serves files from a dictionary and
// records every URL asked for, in order.

import assert from "node:assert/strict";
import { beforeEach, test } from "node:test";

import { SCHEMA_VERSION, loadSite, routeDetailLoader } from "../js/data.js";

let requested;

/** Serve `files` (url -> parsed JSON); anything else is a 404. */
function serve(files) {
  requested = [];
  globalThis.fetch = async (url) => {
    requested.push(url);
    if (!(url in files)) {
      return { ok: false, status: 404 };
    }
    return { ok: true, status: 200, json: async () => structuredClone(files[url]) };
  };
}

const STATUS = { schema_version: 1, snapshot: "2026-11-25T121123Z.json" };
const ROUTES = [{ key: "bus-2" }, { key: "rail-AIR" }];
const NETWORK = { type: "FeatureCollection", features: [{ id: "network" }] };
const STARTS = { type: "FeatureCollection", features: [{ id: "starts" }] };
const SITE = {
  "data/status.json": STATUS,
  "data/routes.json": ROUTES,
  "data/network.geojson": NETWORK,
  "data/starts.geojson": STARTS,
};
const BUS_2 = { schema_version: 1, key: "bus-2", detours: [] };
const RAIL_AIR = { schema_version: 1, key: "rail-AIR", detours: [] };

beforeEach(() => serve({}));

test("SCHEMA_VERSION matches the Python contract's", () => {
  assert.equal(SCHEMA_VERSION, 1);
});

// --- loadSite ---------------------------------------------------------------

test("loadSite: returns every overview file, status first", async () => {
  serve(SITE);
  assert.deepEqual(await loadSite(), {
    status: STATUS,
    routes: ROUTES,
    network: NETWORK,
    starts: STARTS,
  });
  assert.deepEqual(requested, [
    "data/status.json",
    "data/routes.json",
    "data/network.geojson",
    "data/starts.geojson",
  ]);
});

test("loadSite: an unknown schema_version fails before the other files", async () => {
  serve({ ...SITE, "data/status.json": { ...STATUS, schema_version: 2 } });
  await assert.rejects(loadSite(), {
    message:
      "data/status.json has schema_version 2; this page reads 1.\n" +
      "Re-export the data (or reload the page):\n" +
      "uv run python -m septa_detours.export site",
  });
  assert.deepEqual(requested, ["data/status.json"]);
});

test("loadSite: a status.json without schema_version is refused", async () => {
  const { schema_version: _, ...noVersion } = STATUS;
  serve({ ...SITE, "data/status.json": noVersion });
  await assert.rejects(loadSite(), /has schema_version undefined; this page reads 1/);
});

test("loadSite: a missing file names the URL, the status and the commands", async () => {
  const { "data/network.geojson": _, ...withoutNetwork } = SITE;
  serve(withoutNetwork);
  await assert.rejects(loadSite(), {
    message:
      "Could not load data/network.geojson (HTTP 404).\nMake it first:\n" +
      "uv run python -m septa_detours.match\n" +
      "uv run python -m septa_detours.export site",
  });
});

test("loadSite: a missing status.json stops everything", async () => {
  serve({});
  await assert.rejects(loadSite(), /Could not load data\/status\.json \(HTTP 404\)/);
  assert.deepEqual(requested, ["data/status.json"]);
});

// --- routeDetailLoader --------------------------------------------------------

test("routeDetailLoader: loads a route's file", async () => {
  serve({ "data/routes/bus-2.json": BUS_2 });
  const load = routeDetailLoader();
  assert.deepEqual(await load("bus-2"), BUS_2);
  assert.deepEqual(requested, ["data/routes/bus-2.json"]);
});

test("routeDetailLoader: each file is fetched once, even while loading", async () => {
  serve({ "data/routes/bus-2.json": BUS_2, "data/routes/rail-AIR.json": RAIL_AIR });
  const load = routeDetailLoader();
  const first = load("bus-2");
  const second = load("bus-2"); // before the first has finished
  assert.equal(first, second);
  await first;
  await load("bus-2");
  assert.deepEqual(await load("rail-AIR"), RAIL_AIR);
  assert.deepEqual(requested, ["data/routes/bus-2.json", "data/routes/rail-AIR.json"]);
});

test("routeDetailLoader: separate loaders have separate caches", async () => {
  serve({ "data/routes/bus-2.json": BUS_2 });
  await routeDetailLoader()("bus-2");
  await routeDetailLoader()("bus-2");
  assert.equal(requested.length, 2);
});

test("routeDetailLoader: a failed load is retried next time", async () => {
  serve({});
  const load = routeDetailLoader();
  await assert.rejects(load("bus-2"), /Could not load data\/routes\/bus-2\.json \(HTTP 404\)/);
  serve({ "data/routes/bus-2.json": BUS_2 });
  assert.deepEqual(await load("bus-2"), BUS_2);
});

test("routeDetailLoader: a stale route file is refused, then retried", async () => {
  serve({ "data/routes/bus-2.json": { ...BUS_2, schema_version: 0 } });
  const load = routeDetailLoader();
  await assert.rejects(
    load("bus-2"),
    /data\/routes\/bus-2\.json has schema_version 0; this page reads 1/,
  );
  serve({ "data/routes/bus-2.json": BUS_2 });
  assert.deepEqual(await load("bus-2"), BUS_2);
});
