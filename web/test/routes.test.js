// Tests for web/js/routes.js. Run: node --test web/test/

import assert from "node:assert/strict";
import { test } from "node:test";

import { detouredKeys, detouredRoutes, routesBounds } from "../js/routes.js";

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
