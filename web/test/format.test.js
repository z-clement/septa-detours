// Tests for web/js/format.js. Run from the repo root: node --test web/test/
//
// Uses Node's built-in test runner and assert (no npm, no dependencies).

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  describeDetour,
  describeRoute,
  formatTime,
  plural,
  routeLabel,
  statusLine,
} from "../js/format.js";

// Times must show in SEPTA_TIME_ZONE whatever the machine's own zone. On a
// machine set to New York, a missing `timeZone` option would still pass, so
// pretend to be far away (Node applies a TZ change at runtime).
process.env.TZ = "Asia/Tokyo";

// Route 2's real 17th & Washington detour message.
const ROUTE_2_MESSAGE =
  "7am - 4pm Mon thru Fri, 11/27/26, SB via 17th, Left on Washington, " +
  "Right on Broad, Right on Passyunk, Left on 17th, Reg Rt";

// --- plural -----------------------------------------------------------------

test("plural: one is singular, zero and many are plural", () => {
  assert.equal(plural(1, "route"), "1 route");
  assert.equal(plural(0, "route"), "0 routes");
  assert.equal(plural(2, "route"), "2 routes");
  assert.equal(plural(134, "detour start point"), "134 detour start points");
});

test("plural: an irregular plural form", () => {
  assert.equal(plural(1, "bus", "buses"), "1 bus");
  assert.equal(plural(3, "bus", "buses"), "3 buses");
});

// --- formatTime -------------------------------------------------------------

test("formatTime: shows SEPTA local time, winter and summer", () => {
  assert.equal(formatTime("2026-11-25T15:00:00-05:00"), "Nov 25, 2026, 3:00 PM");
  assert.equal(formatTime("2026-07-04T08:05:00-04:00"), "Jul 4, 2026, 8:05 AM");
});

test("formatTime: an instant given in UTC is shown in Philadelphia time", () => {
  assert.equal(formatTime("2026-11-25T20:00:00Z"), "Nov 25, 2026, 3:00 PM");
  assert.equal(formatTime("2026-11-26T04:59:00Z"), "Nov 25, 2026, 11:59 PM");
});

test("formatTime: missing is (unknown), whether undefined or null", () => {
  assert.equal(formatTime(undefined), "(unknown)");
  assert.equal(formatTime(null), "(unknown)");
});

// --- The data contract's text --------------------------------------------------

// Real status.json counts (snapshot 2026-11-25T121123Z), as export site
// should write them.
const STATUS = {
  schema_version: 2,
  generated_at: "2026-11-25T19:59:53Z",
  snapshot: "2026-11-25T121123Z.json",
  snapshot_fetched_at: "2026-11-25T12:11:23Z",
  gtfs: { bus: "v202611220", rail: "v202611220" },
  detours: { total: 166, matched: 161, placed: 134 },
  unmatched: [],
};

// Real routes.json entry and detour object for route 2.
const ROUTE_2 = {
  key: "bus-2",
  feed: "bus",
  route_id: "2",
  short_name: "2",
  long_name: "20-Johnston to Pulaski-Hunting Park",
  mode: "bus",
  color: "#1A1818",
  text_color: "#FFFFFF",
  has_shapes: true,
  bounds: [
    [-75.18186, 39.91357],
    [-75.15575, 40.02279],
  ],
  detours: { total: 7, placed: 7 },
};
const ROUTE_2_DETOUR = {
  source_key: "5d0d22dfe7d86935",
  route: "bus-2",
  status: "complete",
  direction: "SB",
  direction_id: 0,
  location_start: "17th & Washington",
  location_end: "17th & Mifflin",
  start: "2026-11-11T06:30:00-05:00",
  end: "2026-11-27T16:00:00-05:00",
  reason: "Contractor",
  message: ROUTE_2_MESSAGE,
  issues: [],
  start_point: { lon: -75.1715984, lat: 39.9384641, node_id: 110024066 },
  shape_ids: ["317310", "317308", "317309"],
};

test("routeLabel: short and long name, or short name alone", () => {
  assert.equal(routeLabel(ROUTE_2), "Route 2 20-Johnston to Pulaski-Hunting Park");
  assert.equal(routeLabel({ ...ROUTE_2, short_name: "K", long_name: null }), "Route K");
});

test("statusLine: real counts, every part", () => {
  assert.equal(
    statusLine(STATUS),
    "Detours as of Nov 25, 2026, 7:11 AM: 166 total, 134 on the map, " +
      "27 without a location, 5 not matched to a route",
  );
});

test("statusLine: zero parts are left out", () => {
  const allPlaced = { ...STATUS, detours: { total: 5, matched: 5, placed: 5 } };
  assert.equal(statusLine(allPlaced), "Detours as of Nov 25, 2026, 7:11 AM: 5 total, 5 on the map");
  const unmatchedOnly = { ...STATUS, detours: { total: 3, matched: 0, placed: 0 } };
  assert.equal(
    statusLine(unmatchedOnly),
    "Detours as of Nov 25, 2026, 7:11 AM: 3 total, 0 on the map, 3 not matched to a route",
  );
});

test("statusLine: no detours", () => {
  const none = { ...STATUS, detours: { total: 0, matched: 0, placed: 0 } };
  assert.equal(statusLine(none), "No detours as of Nov 25, 2026, 7:11 AM");
});

test("statusLine: a hand-named snapshot shows its name", () => {
  const mine = { ...STATUS, snapshot: "mine.json", snapshot_fetched_at: null };
  assert.equal(statusLine(mine).split(":")[0], "Detours in mine.json");
});

test("describeDetour: a real detour, whole text", () => {
  assert.equal(
    describeDetour(ROUTE_2_DETOUR, ROUTE_2),
    [
      "Route 2 20-Johnston to Pulaski-Hunting Park, SB",
      "From: 17th & Washington",
      "To: 17th & Mifflin",
      "Nov 11, 2026, 6:30 AM to Nov 27, 2026, 4:00 PM",
      "Reason: Contractor",
      "Status: complete",
      "Issues: (none)",
      "",
      ROUTE_2_MESSAGE,
      "",
      "source_key 5d0d22dfe7d86935, OSM node 110024066",
    ].join("\n"),
  );
});

test("describeDetour: nulls from plain JSON get fallbacks; issues are joined", () => {
  const unknown = {
    ...ROUTE_2_DETOUR,
    status: "partial",
    direction: null,
    location_start: null,
    location_end: null,
    start: null,
    end: null,
    reason: null,
    issues: ["direction: none found in message", "start: no crossing near the route"],
    start_point: null,
  };
  const lines = describeDetour(unknown, ROUTE_2).split("\n");
  assert.deepEqual(lines.slice(0, 7), [
    "Route 2 20-Johnston to Pulaski-Hunting Park, (no direction)",
    "From: (unknown)",
    "To: (unknown)",
    "(unknown) to (unknown)",
    "Reason: (none given)",
    "Status: partial",
    "Issues: direction: none found in message; start: no crossing near the route",
  ]);
  assert.equal(lines.at(-1), "source_key 5d0d22dfe7d86935, not placed");
});

test("describeRoute: with detours, one detour, and none", () => {
  assert.equal(
    describeRoute(ROUTE_2),
    "Route 2 20-Johnston to Pulaski-Hunting Park\n7 detours (7 on the map)",
  );
  const one = { ...ROUTE_2, detours: { total: 1, placed: 0 } };
  assert.equal(describeRoute(one).split("\n")[1], "1 detour (0 on the map)");
  const none = { ...ROUTE_2, detours: { total: 0, placed: 0 } };
  assert.equal(describeRoute(none).split("\n")[1], "No detours");
});
