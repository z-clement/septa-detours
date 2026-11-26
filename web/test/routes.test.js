// Tests for web/js/routes.js. Run: node --test web/test/

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  detouredKeys,
  detouredNow,
  detouredRoutes,
  routesBounds,
  timingCounts,
} from "../js/routes.js";

/** A routes.json entry with just the fields routes.js reads. */
function route(key, total, placed, bounds) {
  return { key, detours: { total, placed }, bounds };
}

// Real-looking bounds ([west, south], [east, north]); every edge distinct
// so a min/max or lon/lat swap shows.
const BUS_2 = route("bus-2", 7, 7, [
  [-75.18186, 39.91357],
  [-75.15575, 40.02279],
]);
const BUS_21 = route("bus-21", 0, 0, [
  [-75.26, 39.94],
  [-75.14, 39.97],
]);
const BUS_49 = route("bus-49", 2, 0, [
  [-75.22, 39.92],
  [-75.13, 39.99],
]);
const MANN = route("bus-MANN", 1, 0, null);
const AIR = route("rail-AIR", 0, 0, [
  [-75.25, 39.87],
  [-75.16, 39.96],
]);

test("detouredKeys: any matched detour counts, placed or not; catalog order", () => {
  assert.deepEqual(detouredKeys([BUS_2, BUS_21, BUS_49, MANN, AIR]), [
    "bus-2",
    "bus-49",
    "bus-MANN",
  ]);
});

test("detouredRoutes: the routes themselves, same rule and order", () => {
  assert.deepEqual(detouredRoutes([BUS_2, BUS_21, BUS_49, MANN, AIR]), [BUS_2, BUS_49, MANN]);
});

test("detouredKeys: none", () => {
  assert.deepEqual(detouredKeys([BUS_21, AIR]), []);
  assert.deepEqual(detouredKeys([]), []);
});

test("routesBounds: one route is its own bounds", () => {
  assert.deepEqual(routesBounds([BUS_2]), BUS_2.bounds);
});

test("routesBounds: the box around several routes", () => {
  assert.deepEqual(routesBounds([BUS_2, BUS_21, AIR]), [
    [-75.26, 39.87],
    [-75.14, 40.02279],
  ]);
});

test("routesBounds: routes without bounds are skipped", () => {
  assert.deepEqual(routesBounds([MANN, BUS_49]), BUS_49.bounds);
});

test("routesBounds: no bounds at all is null", () => {
  assert.equal(routesBounds([MANN]), null);
  assert.equal(routesBounds([]), null);
});

// --- timingCounts, detouredNow ------------------------------------------------

// Route 2's real routes.json windows (snapshot 121123Z), in order. At NOW
// (Nov 25, 9 AM Philadelphia), 2 are active, 4 upcoming, 1 ended: all
// different, so a mixed-up count shows.
const ROUTE_2_WINDOWS = [
  ["2026-11-11T06:30:00-05:00", "2026-11-27T16:00:00-05:00"],
  ["2026-11-19T10:00:00-05:00", "2026-12-01T23:59:00-05:00"],
  ["2026-11-25T15:00:00-05:00", "2026-11-26T02:00:00-05:00"],
  ["2026-11-25T15:00:00-05:00", "2026-11-26T02:00:00-05:00"],
  ["2026-11-26T02:00:00-05:00", "2026-11-26T22:00:00-05:00"],
  ["2026-11-26T02:00:00-05:00", "2026-11-26T22:00:00-05:00"],
  ["2026-11-24T19:33:00-05:00", "2026-11-25T08:00:00-05:00"],
];
const NOW = new Date("2026-11-25T14:00:00Z");
const ACTIVE = ROUTE_2_WINDOWS[0];
const UPCOMING = ROUTE_2_WINDOWS[2];
const ENDED = ROUTE_2_WINDOWS[6];
const UNKNOWN = [null, "2026-11-27T16:00:00-05:00"];

/** A routes.json entry with just its key and detour windows. */
function windowed(key, windows) {
  return { key, detours: { total: windows.length, placed: 0, windows } };
}

test("timingCounts: route 2's real windows", () => {
  assert.deepEqual(timingCounts(windowed("bus-2", ROUTE_2_WINDOWS), NOW), {
    active: 2,
    upcoming: 4,
    ended: 1,
    unknown: 0,
  });
});

test("timingCounts: a missing time counts as unknown", () => {
  assert.deepEqual(timingCounts(windowed("bus-9", [UNKNOWN, ACTIVE, UNKNOWN]), NOW), {
    active: 1,
    upcoming: 0,
    ended: 0,
    unknown: 2,
  });
});

test("timingCounts: no detours is all zeros", () => {
  assert.deepEqual(timingCounts(windowed("bus-21", []), NOW), {
    active: 0,
    upcoming: 0,
    ended: 0,
    unknown: 0,
  });
});

test("timingCounts: depends on now", () => {
  // The snapshot's own time: the last window hadn't ended yet.
  const atSnapshot = new Date("2026-11-25T12:11:23Z");
  assert.equal(timingCounts(windowed("bus-2", ROUTE_2_WINDOWS), atSnapshot).active, 3);
});

test("detouredNow: most active first, ties in catalog order, inactive left out", () => {
  // Catalog order, deliberately not alphabetical by key.
  const bus64 = windowed("bus-64", [ACTIVE, UPCOMING]); // 1 active
  const bus2 = windowed("bus-2", ROUTE_2_WINDOWS); // 2 active
  const bus19 = windowed("bus-19", [UPCOMING, ENDED, UNKNOWN]); // none active
  const bus21 = windowed("bus-21", []);
  const bus108 = windowed("bus-108", [ENDED, ACTIVE]); // 1 active
  const rail = windowed("rail-AIR", [ACTIVE, ACTIVE, ACTIVE]); // 3 active
  assert.deepEqual(detouredNow([bus64, bus2, bus19, bus21, bus108, rail], NOW), [
    { route: rail, active: 3 },
    { route: bus2, active: 2 },
    { route: bus64, active: 1 },
    { route: bus108, active: 1 },
  ]);
});

test("detouredNow: nothing active is empty", () => {
  assert.deepEqual(detouredNow([windowed("bus-19", [UPCOMING, ENDED])], NOW), []);
  assert.deepEqual(detouredNow([], NOW), []);
});
