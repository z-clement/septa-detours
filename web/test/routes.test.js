// Tests for web/js/routes.js. Run: node --test web/test/

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  clickChoices,
  detouredKeys,
  detouredNow,
  detouredRoutes,
  groupByMode,
  routesBounds,
  searchRoutes,
  timingCounts,
  visibleRoutes,
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

// --- groupByMode ------------------------------------------------------------

/** A routes.json entry with just its key and mode. */
function moded(key, mode) {
  return { key, mode };
}

// Real keys, in routes.json order (metro, trolley, trackless, bus, rail);
// unequal group sizes so a mixed-up group shows.
const L1 = moded("bus-L1", "metro");
const B1 = moded("bus-B1", "metro");
const T1 = moded("bus-T1", "trolley");
const TRACKLESS_59 = moded("bus-59", "trackless");
const BUS_2_MODED = moded("bus-2", "bus");
const BUS_21_MODED = moded("bus-21", "bus");
const BUS_K = moded("bus-K", "bus");
const AIR_MODED = moded("rail-AIR", "rail");

test("groupByMode: groups in catalog order, routes in catalog order", () => {
  const routes = [B1, L1, T1, TRACKLESS_59, BUS_2_MODED, BUS_21_MODED, BUS_K, AIR_MODED];
  assert.deepEqual(groupByMode(routes), [
    { mode: "metro", routes: [B1, L1] },
    { mode: "trolley", routes: [T1] },
    { mode: "trackless", routes: [TRACKLESS_59] },
    { mode: "bus", routes: [BUS_2_MODED, BUS_21_MODED, BUS_K] },
    { mode: "rail", routes: [AIR_MODED] },
  ]);
});

test("groupByMode: the order comes from the routes, not a fixed mode list", () => {
  assert.deepEqual(groupByMode([AIR_MODED, BUS_K, B1]), [
    { mode: "rail", routes: [AIR_MODED] },
    { mode: "bus", routes: [BUS_K] },
    { mode: "metro", routes: [B1] },
  ]);
});

test("groupByMode: only modes with routes get a group", () => {
  assert.deepEqual(groupByMode([BUS_2_MODED, AIR_MODED]), [
    { mode: "bus", routes: [BUS_2_MODED] },
    { mode: "rail", routes: [AIR_MODED] },
  ]);
  assert.deepEqual(groupByMode([]), []);
});

test("groupByMode: a mode in two runs is one group, at its first place", () => {
  assert.deepEqual(groupByMode([BUS_2_MODED, AIR_MODED, BUS_K]), [
    { mode: "bus", routes: [BUS_2_MODED, BUS_K] },
    { mode: "rail", routes: [AIR_MODED] },
  ]);
});

test("groupByMode: keeps the route objects themselves", () => {
  const [group] = groupByMode([BUS_K]);
  assert.equal(group.routes[0], BUS_K);
});

const CATALOG_MODES = ["metro", "trolley", "trackless", "bus", "rail"];

test("groupByMode: a mode order puts the groups in it, routes keep their order", () => {
  // Ranked search results ("k" puts K first): groups still in catalog
  // order, but K stays first among the buses.
  assert.deepEqual(groupByMode([BUS_K, L1, BUS_2_MODED, AIR_MODED, T1], CATALOG_MODES), [
    { mode: "metro", routes: [L1] },
    { mode: "trolley", routes: [T1] },
    { mode: "bus", routes: [BUS_K, BUS_2_MODED] },
    { mode: "rail", routes: [AIR_MODED] },
  ]);
});

test("groupByMode: modes in the order without routes get no group", () => {
  assert.deepEqual(groupByMode([BUS_K], CATALOG_MODES), [{ mode: "bus", routes: [BUS_K] }]);
  assert.deepEqual(groupByMode([], CATALOG_MODES), []);
});

test("groupByMode: a mode missing from the order comes after, by first route", () => {
  const ferry = moded("bus-FERRY", "ferry");
  const tram = moded("bus-TRAM", "tram");
  assert.deepEqual(groupByMode([tram, BUS_K, ferry, L1], ["metro", "bus"]), [
    { mode: "metro", routes: [L1] },
    { mode: "bus", routes: [BUS_K] },
    { mode: "tram", routes: [tram] },
    { mode: "ferry", routes: [ferry] },
  ]);
});

// --- searchRoutes -----------------------------------------------------------

/** A routes.json entry with just its key and names. */
function named(key, shortName, longName) {
  return { key, short_name: shortName, long_name: longName };
}

// Real names, in routes.json order.
const N_L1 = named("bus-L1", "L1", "Market-Frankford Line All Stops");
const N_2 = named("bus-2", "2", "20-Johnston to Pulaski-Hunting Park");
const N_5 = named("bus-5", "5", "2nd-Market to Frankford Transit Ctr");
const N_12 = named("bus-12", "12", "Columbus-Dock to 50th-Woodland");
const N_21 = named("bus-21", "21", "Columbus-Dock to 69th St TC");
const N_204 = named("bus-204", "204", "Eagleview to Paoli Train Station");
const N_B1_OWL = named("bus-B1_OWL", "B1 OWL", "Midnight-5am Service (Bus) for B1");
const N_K = named("bus-K", "K", "Ridge-Midvale to Arrott Transit Ctr");
const N_L1_OWL = named("bus-L1_OWL", "L1 OWL", "Midnight-5am Service (Bus) for L1");
const N_AIR = named("rail-AIR", "AIR", "Airport Line");
const NAMED = [N_L1, N_2, N_5, N_12, N_21, N_204, N_B1_OWL, N_K, N_L1_OWL, N_AIR];

test("searchRoutes: a number matches route numbers from the start", () => {
  // Not 12 (a 2 inside), not 5 ("2nd-Market": a long name starting with 2).
  assert.deepEqual(searchRoutes(NAMED, "2"), [N_2, N_21, N_204]);
  assert.deepEqual(searchRoutes(NAMED, "20"), [N_204]);
});

test("searchRoutes: a number never matches inside a long name", () => {
  // "69th St TC" and "50th-Woodland" are street numbers, not routes.
  assert.deepEqual(searchRoutes(NAMED, "69"), []);
  assert.deepEqual(searchRoutes(NAMED, "50"), []);
});

test("searchRoutes: text matches anywhere in either name", () => {
  assert.deepEqual(searchRoutes(NAMED, "owl"), [N_B1_OWL, N_L1_OWL]); // short name
  assert.deepEqual(searchRoutes(NAMED, "columbus"), [N_12, N_21]); // long name start
  assert.deepEqual(searchRoutes(NAMED, "transit"), [N_5, N_K]); // long name middle
  assert.deepEqual(searchRoutes(NAMED, "air"), [N_AIR]); // both names
});

test("searchRoutes: letters and digits together are text, matched anywhere", () => {
  // L1 itself, and the owl bus whose long name ends "for L1".
  assert.deepEqual(searchRoutes(NAMED, "L1"), [N_L1, N_L1_OWL]);
  // "5am" is text, so it matches inside "Midnight-5am".
  assert.deepEqual(searchRoutes(NAMED, "5am"), [N_B1_OWL, N_L1_OWL]);
});

test("searchRoutes: case and surrounding spaces are ignored", () => {
  assert.deepEqual(searchRoutes(NAMED, "  AiRpOrT "), [N_AIR]);
  assert.deepEqual(searchRoutes(NAMED, " 2 "), [N_2, N_21, N_204]);
  assert.deepEqual(searchRoutes(NAMED, "l1 owl"), [N_L1_OWL]);
});

test("searchRoutes: a blank query keeps every route, in a new list", () => {
  for (const query of ["", "   "]) {
    const result = searchRoutes(NAMED, query);
    assert.deepEqual(result, NAMED);
    assert.notEqual(result, NAMED); // the caller may sort it; NAMED stays put
  }
});

test("searchRoutes: no match is empty", () => {
  assert.deepEqual(searchRoutes(NAMED, "ferry"), []);
  assert.deepEqual(searchRoutes([], "2"), []);
});

test("searchRoutes: a route with no long name matches on its short name only", () => {
  const noLong = named("bus-X9", "X9", null);
  assert.deepEqual(searchRoutes([noLong, N_K], "x9"), [noLong]);
  assert.deepEqual(searchRoutes([noLong, N_K], "null"), []); // not the text "null"
});

test("searchRoutes: a short name starting with the text comes first", () => {
  // Route K, then every "k" inside a name (Frankford, Hunting Park, Dock).
  assert.deepEqual(searchRoutes(NAMED, "k"), [N_K, N_L1, N_2, N_5, N_12, N_21]);
});

test("searchRoutes: both parts keep catalog order", () => {
  // Starting with "l": L1, L1 OWL. Then the rest with an "l" anywhere
  // (Pulaski, Columbus, Paoli, owl, Midvale, Line), in catalog order.
  assert.deepEqual(searchRoutes(NAMED, "l"), [
    N_L1,
    N_L1_OWL,
    N_2,
    N_12,
    N_21,
    N_204,
    N_B1_OWL,
    N_K,
    N_AIR,
  ]);
});

/** A routes.json entry with its key, names and mode. */
function full(key, shortName, longName, mode) {
  return { key, short_name: shortName, long_name: longName, mode };
}

// Real names and modes, in routes.json order.
const F_L1 = full("bus-L1", "L1", "Market-Frankford Line All Stops", "metro");
const F_T1 = full("bus-T1", "T1", "13th St to 63rd-Malvern/Overbrook", "trolley");
const F_59 = full("bus-59", "59", "Castor-Bustleton to Arrott TC", "trackless");
const F_2 = full("bus-2", "2", "20-Johnston to Pulaski-Hunting Park", "bus");
const F_5 = full("bus-5", "5", "2nd-Market to Frankford Transit Ctr", "bus");
const F_23 = full("bus-23", "23", "11th Market to Chestnut Hill", "bus");
const F_AIR = full("rail-AIR", "AIR", "Airport Line", "rail");
const FULL = [F_L1, F_T1, F_59, F_2, F_5, F_23, F_AIR];
const ALL_MODES = new Set(["metro", "trolley", "trackless", "bus", "rail"]);

test("visibleRoutes: a route must match the search and have its mode on", () => {
  assert.deepEqual(visibleRoutes(FULL, "market", new Set(["bus"])), [F_5, F_23]);
  assert.deepEqual(visibleRoutes(FULL, "market", new Set(["metro", "bus"])), [F_L1, F_5, F_23]);
});

test("visibleRoutes: blank search keeps the modes that are on, catalog order", () => {
  // The Set's own order doesn't matter: rail is listed first here.
  assert.deepEqual(visibleRoutes(FULL, "", new Set(["rail", "trolley"])), [F_T1, F_AIR]);
});

test("visibleRoutes: every mode on and a blank search is the whole catalog", () => {
  assert.deepEqual(visibleRoutes(FULL, "  ", ALL_MODES), FULL);
});

test("visibleRoutes: no modes on lists nothing", () => {
  assert.deepEqual(visibleRoutes(FULL, "", new Set()), []);
  assert.deepEqual(visibleRoutes(FULL, "market", new Set()), []);
});

test("visibleRoutes: a mode on but nothing of it matching lists nothing of it", () => {
  assert.deepEqual(visibleRoutes(FULL, "market", new Set(["rail", "trackless"])), []);
});

// --- clickChoices -------------------------------------------------------------

/** A clicked feature with just the properties clickChoices reads. */
function hit(key, sourceKey) {
  return { properties: sourceKey === undefined ? { key } : { key, source_key: sourceKey } };
}

test("clickChoices: nothing under the click, no choices", () => {
  assert.deepEqual(clickChoices([], []), []);
});

test("clickChoices: lines give one choice per route, first seen first", () => {
  // A route's directions and shapes overlap, so its key repeats.
  const lines = [hit("bus-21"), hit("bus-42"), hit("bus-21"), hit("bus-9"), hit("bus-42")];
  assert.deepEqual(clickChoices([], lines), [
    { key: "bus-21", detour: null },
    { key: "bus-42", detour: null },
    { key: "bus-9", detour: null },
  ]);
});

test("clickChoices: dots give one choice per detour, and lines don't count", () => {
  const dots = [hit("bus-2", "5d0d22dfe7d86935"), hit("bus-2", "c1"), hit("bus-49", "c2")];
  assert.deepEqual(clickChoices(dots, [hit("bus-21")]), [
    { key: "bus-2", detour: "5d0d22dfe7d86935" },
    { key: "bus-2", detour: "c1" },
    { key: "bus-49", detour: "c2" },
  ]);
});

test("clickChoices: direction twins (same source_key, same dot) are one choice", () => {
  // Route L1 OWL's real EB/WB stop closures at 5th & Market.
  const twin = () => hit("bus-L1_OWL", "a08563ebaa011c5d");
  assert.deepEqual(clickChoices([twin(), twin()], []), [
    { key: "bus-L1_OWL", detour: "a08563ebaa011c5d" },
  ]);
});

test("clickChoices: the same source_key on two routes is two choices", () => {
  const dots = [hit("bus-2", "abc"), hit("bus-21", "abc")];
  assert.deepEqual(
    clickChoices(dots, []).map((c) => c.key),
    ["bus-2", "bus-21"],
  );
});
