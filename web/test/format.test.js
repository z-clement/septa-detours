// Tests for web/js/format.js. Run from the repo root: node --test web/test/
//
// Uses Node's built-in test runner and assert (no npm, no dependencies).

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  describeLine,
  describeStart,
  formatTime,
  plural,
  summarize,
} from "../js/format.js";

// Times must show in SEPTA_TIME_ZONE whatever the machine's own zone. On a
// machine set to New York, a missing `timeZone` option would still pass, so
// pretend to be far away (Node applies a TZ change at runtime).
process.env.TZ = "Asia/Tokyo";

/** Drop null properties, as MapLibre does for clicked features. */
function asClicked(properties) {
  return Object.fromEntries(
    Object.entries(properties).filter(([, value]) => value !== null),
  );
}

// Real properties of route 2's 17th & Washington start point
// (web/data/detours.geojson from snapshot 2026-11-25T121123Z).
const ROUTE_2_START = {
  feed: "bus",
  route_id: "2",
  route_short_name: "2",
  route_long_name: "20-Johnston to Pulaski-Hunting Park",
  route_type: 3,
  route_color: "#1A1818",
  route_text_color: "#FFFFFF",
  source_key: "5d0d22dfe7d86935",
  status: "complete",
  direction: "SB",
  location_start: "17th & Washington",
  location_end: "17th & Mifflin",
  start: "2026-11-11T06:30:00-05:00",
  end: "2026-11-27T16:00:00-05:00",
  reason: "Contractor",
  message:
    "7am - 4pm Mon thru Fri, 11/27/26, SB via 17th, Left on Washington, " +
    "Right on Broad, Right on Passyunk, Left on 17th, Reg Rt",
  issues: null,
  node_id: 110024066,
};

// One of route 2's real detoured lines.
const ROUTE_2_LINE = {
  feed: "bus",
  route_id: "2",
  route_short_name: "2",
  route_long_name: "20-Johnston to Pulaski-Hunting Park",
  route_type: 3,
  route_color: "#1A1818",
  route_text_color: "#FFFFFF",
  shape_id: "317310",
  direction_id: 0,
  detour_count: 4,
};

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

// --- describeStart ----------------------------------------------------------

test("describeStart: a real start point, whole text", () => {
  assert.equal(
    describeStart(asClicked(ROUTE_2_START)),
    [
      "Route 2 20-Johnston to Pulaski-Hunting Park, SB",
      "From: 17th & Washington",
      "To: 17th & Mifflin",
      "Nov 11, 2026, 6:30 AM to Nov 27, 2026, 4:00 PM",
      "Reason: Contractor",
      "Status: complete",
      "Issues: (none)",
      "",
      ROUTE_2_START.message,
      "",
      "source_key 5d0d22dfe7d86935, OSM node 110024066",
    ].join("\n"),
  );
});

test("describeStart: every missing value gets its own fallback", () => {
  const unknown = asClicked({
    ...ROUTE_2_START,
    status: "unknown",
    direction: null,
    location_start: null,
    location_end: null,
    start: null,
    end: null,
    reason: null,
    issues: "direction: none found in message; shapes: no direction in notice",
  });
  const lines = describeStart(unknown).split("\n");
  assert.deepEqual(lines.slice(0, 7), [
    "Route 2 20-Johnston to Pulaski-Hunting Park, (no direction)",
    "From: (unknown)",
    "To: (unknown)",
    "(unknown) to (unknown)",
    "Reason: (none given)",
    "Status: unknown",
    "Issues: direction: none found in message; shapes: no direction in notice",
  ]);
});

// --- describeLine -----------------------------------------------------------

test("describeLine: a real line, whole text", () => {
  assert.equal(
    describeLine(asClicked(ROUTE_2_LINE)),
    "Route 2 20-Johnston to Pulaski-Hunting Park\n" +
      "direction 0, shape 317310\n" +
      "4 detours list this shape",
  );
});

test("describeLine: one detour is singular", () => {
  const text = describeLine(asClicked({ ...ROUTE_2_LINE, detour_count: 1 }));
  assert.equal(text.split("\n")[2], "1 detour lists this shape");
});

test("describeLine: missing direction_id is (none), but 0 stays 0", () => {
  const missing = describeLine(asClicked({ ...ROUTE_2_LINE, direction_id: null }));
  assert.equal(missing.split("\n")[1], "direction (none), shape 317310");
  const zero = describeLine(asClicked({ ...ROUTE_2_LINE, direction_id: 0 }));
  assert.equal(zero.split("\n")[1], "direction 0, shape 317310");
});

// --- summarize --------------------------------------------------------------

function point(routeId) {
  return {
    type: "Feature",
    geometry: { type: "Point", coordinates: [-75.1716, 39.9385] },
    properties: { route_id: routeId },
  };
}

function line(routeId) {
  return {
    type: "Feature",
    geometry: {
      type: "LineString",
      coordinates: [
        [-75.1716, 39.9405],
        [-75.1716, 39.9365],
      ],
    },
    properties: { route_id: routeId },
  };
}

test("summarize: empty is a status, not a count", () => {
  assert.equal(summarize({ type: "FeatureCollection", features: [] }), "No detours to show.");
});

test("summarize: one of each is singular", () => {
  const collection = { type: "FeatureCollection", features: [line("2"), point("2")] };
  assert.equal(summarize(collection), "1 detour start point on 1 route");
});

test("summarize: counts points, and distinct routes over lines and points", () => {
  const collection = {
    type: "FeatureCollection",
    features: [line("2"), line("2"), line("31"), point("2"), point("2"), line("64")],
  };
  assert.equal(summarize(collection), "2 detour start points on 3 routes");
});

test("summarize: a route with only an unplaced detour has no points", () => {
  const collection = { type: "FeatureCollection", features: [line("49")] };
  assert.equal(summarize(collection), "0 detour start points on 1 route");
});
