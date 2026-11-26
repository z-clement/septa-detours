// Tests for web/js/format.js. Run from the repo root: node --test web/test/
//
// Uses Node's built-in test runner and assert (no npm, no dependencies).

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  choiceText,
  TIMING_WORDS,
  apiRouteName,
  detourHeadline,
  detourPlaces,
  directionLabel,
  directionSummary,
  focusAnnouncement,
  formatTime,
  modeLabel,
  plural,
  routeLabel,
  statusLine,
  timingHeading,
  timingSummary,
  unmatchedSummary,
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

// --- modeLabel --------------------------------------------------------------

test("modeLabel: every routes.json mode", () => {
  assert.deepEqual(
    ["metro", "trolley", "trackless", "bus", "rail"].map(modeLabel),
    ["Metro", "Trolleys", "Trackless Trolleys", "Buses", "Regional Rail"],
  );
});

test("modeLabel: an unknown mode shows as itself", () => {
  assert.equal(modeLabel("ferry"), "ferry");
  // Not an Object method found through the prototype chain.
  assert.equal(modeLabel("toString"), "toString");
});

// --- timingSummary ----------------------------------------------------------

test("timingSummary: every part, in order, counts unequal so swaps show", () => {
  assert.equal(
    timingSummary({ active: 3, upcoming: 4, ended: 1, unknown: 2 }),
    "3 now, 4 later, 1 ended, 2 unknown",
  );
});

test("timingSummary: zero parts are left out", () => {
  // Route 2 at the snapshot time (Nov 25, 7:11 AM): 3 active, 4 upcoming.
  assert.equal(timingSummary({ active: 3, upcoming: 4, ended: 0, unknown: 0 }), "3 now, 4 later");
  assert.equal(timingSummary({ active: 0, upcoming: 1, ended: 0, unknown: 0 }), "1 later");
  assert.equal(timingSummary({ active: 0, upcoming: 0, ended: 2, unknown: 1 }), "2 ended, 1 unknown");
});

test("timingSummary: no detours gives an empty string", () => {
  assert.equal(timingSummary({ active: 0, upcoming: 0, ended: 0, unknown: 0 }), "");
});

test("timingSummary: uses TIMING_WORDS", () => {
  assert.deepEqual(TIMING_WORDS, {
    active: "now",
    upcoming: "later",
    ended: "ended",
    unknown: "unknown",
  });
  assert.ok(Object.isFrozen(TIMING_WORDS));
});

// --- apiRouteName -----------------------------------------------------------

test("apiRouteName: each API prefix is dropped", () => {
  assert.equal(apiRouteName("bus_route_L"), "L");
  assert.equal(apiRouteName("bus_route_21"), "21");
  assert.equal(apiRouteName("trolley_route_15"), "15");
});

test("apiRouteName: the name is upper-cased, the prefix only matched at the start", () => {
  assert.equal(apiRouteName("rr_route_mfo"), "MFO");
  assert.equal(apiRouteName("x_bus_route_L"), "x_bus_route_L");
});

test("apiRouteName: an unknown id is shown unchanged", () => {
  assert.equal(apiRouteName("APP"), "APP");
  assert.equal(apiRouteName("ferry_route_1"), "ferry_route_1");
});

// --- unmatchedSummary -------------------------------------------------------

// Route L's real NB detour (status.json `unmatched`, snapshot 121123Z).
const ROUTE_L_NB = {
  source_key: "78237091dd0d62b1",
  route: "bus_route_L",
  status: "complete",
  direction: "NB",
  direction_id: null,
  location_start: "Nedro & 20th St",
  location_end: "Wister btwn Church & Spencer",
  start: "2026-11-23T12:00:00-05:00",
  end: "2026-11-30T16:00:00-05:00",
  reason: "Contractors",
  message:
    "7am - 9pm, Mon - Fri until 11/30/26, NB via Nedro, Right on 20th St, " +
    "Left on Chelten Ave, Right on Wister, Reg Rt",
  issues: ["route: no GTFS route for API route 'bus_route_L' (looked for bus route 'L')"],
  start_point: null,
  shape_ids: [],
};

test("unmatchedSummary: a real detour, whole line", () => {
  assert.equal(
    unmatchedSummary(ROUTE_L_NB),
    "Route L, NB: Nedro & 20th St to Wister btwn Church & Spencer",
  );
});

test("unmatchedSummary: no direction", () => {
  assert.equal(
    unmatchedSummary({ ...ROUTE_L_NB, direction: null }),
    "Route L: Nedro & 20th St to Wister btwn Church & Spencer",
  );
});

test("unmatchedSummary: one location missing leaves out its half", () => {
  assert.equal(
    unmatchedSummary({ ...ROUTE_L_NB, location_end: null }),
    "Route L, NB: Nedro & 20th St",
  );
  assert.equal(
    unmatchedSummary({ ...ROUTE_L_NB, location_start: null }),
    "Route L, NB: to Wister btwn Church & Spencer",
  );
});

test("unmatchedSummary: no location at all", () => {
  assert.equal(
    unmatchedSummary({ ...ROUTE_L_NB, location_start: null, location_end: null }),
    "Route L, NB: location not given",
  );
});

// --- Route panel cards ---------------------------------------------------------

// Route 2's real directions and its first detour (routes/bus-2.json):
// direction_id 0 is Southbound on this route.
const BUS_2_DIRECTIONS = [
  { direction_id: 0, name: "Southbound", destination: "20th-Johnston" },
  { direction_id: 1, name: "Northbound", destination: "Pulaski-Hunting Park" },
];
const BUS_2_SB = {
  source_key: "5d0d22dfe7d86935",
  route: "bus-2",
  direction: "SB",
  direction_id: 0,
  location_start: "17th & Washington",
  location_end: "17th & Mifflin",
};

test("detourPlaces: both, one, or neither location", () => {
  assert.equal(detourPlaces(BUS_2_SB), "17th & Washington to 17th & Mifflin");
  assert.equal(detourPlaces({ ...BUS_2_SB, location_end: null }), "17th & Washington");
  assert.equal(detourPlaces({ ...BUS_2_SB, location_start: null }), "to 17th & Mifflin");
  assert.equal(
    detourPlaces({ ...BUS_2_SB, location_start: null, location_end: null }),
    "location not given",
  );
});

test("detourPlaces: the same place at both ends is said once", () => {
  // Route 49's real stop closure.
  const closure = {
    ...BUS_2_SB,
    location_start: "Market & Schuylkill Ave",
    location_end: "Market & Schuylkill Ave",
  };
  assert.equal(detourPlaces(closure), "Market & Schuylkill Ave");
});

test("directionLabel: the route's name for direction_id, not the API's text", () => {
  assert.equal(directionLabel(BUS_2_SB, BUS_2_DIRECTIONS), "Southbound");
  // direction_id 1 with a mismatched API word: the id wins.
  assert.equal(
    directionLabel({ ...BUS_2_SB, direction_id: 1 }, BUS_2_DIRECTIONS),
    "Northbound",
  );
});

test("directionLabel: falls back to the API's text, then null", () => {
  assert.equal(directionLabel({ ...BUS_2_SB, direction_id: null }, BUS_2_DIRECTIONS), "SB");
  assert.equal(directionLabel({ ...BUS_2_SB, direction_id: 7 }, BUS_2_DIRECTIONS), "SB");
  assert.equal(directionLabel(BUS_2_SB, []), "SB");
  assert.equal(
    directionLabel(BUS_2_SB, [{ direction_id: 0, name: null, destination: null }]),
    "SB",
    "a direction without a name",
  );
  assert.equal(
    directionLabel({ ...BUS_2_SB, direction: null, direction_id: null }, BUS_2_DIRECTIONS),
    null,
  );
});

test("detourHeadline: direction then places; places alone with no direction", () => {
  assert.equal(
    detourHeadline(BUS_2_SB, BUS_2_DIRECTIONS),
    "Southbound: 17th & Washington to 17th & Mifflin",
  );
  assert.equal(
    detourHeadline({ ...BUS_2_SB, direction: null, direction_id: null }, BUS_2_DIRECTIONS),
    "17th & Washington to 17th & Mifflin",
  );
});

test("timingHeading: each group's heading with its count", () => {
  assert.deepEqual(
    [
      timingHeading("active", 2),
      timingHeading("upcoming", 1),
      timingHeading("unknown", 3),
      timingHeading("ended", 9),
    ],
    ["In effect (2)", "Upcoming (1)", "Dates unknown (3)", "Ended (9)"],
  );
});

test("directionSummary: name to destination; either may be missing", () => {
  assert.equal(directionSummary(BUS_2_DIRECTIONS[0]), "Southbound to 20th-Johnston");
  assert.equal(directionSummary({ ...BUS_2_DIRECTIONS[1], destination: null }), "Northbound");
  assert.equal(
    directionSummary({ ...BUS_2_DIRECTIONS[1], name: null }),
    "Direction 1 to Pulaski-Hunting Park",
  );
  assert.equal(directionSummary({ direction_id: 0, name: null, destination: null }), "Direction 0");
});

// --- choiceText (the map's chooser) ---------------------------------------------

test("choiceText: a route choice is its long name, or its label without one", () => {
  assert.equal(
    choiceText({ key: "bus-2", detour: null }, ROUTE_2, null),
    "20-Johnston to Pulaski-Hunting Park",
  );
  assert.equal(
    choiceText({ key: "bus-K", detour: null }, { ...ROUTE_2, short_name: "K", long_name: null }, null),
    "Route K",
  );
});

test("choiceText: a detour choice is its headline once the detail loads", () => {
  const choice = { key: "bus-2", detour: "5d0d22dfe7d86935" };
  const other = { ...ROUTE_2_DETOUR, source_key: "c1", location_start: "Broad & Erie" };
  const detail = { directions: BUS_2_DIRECTIONS, detours: [other, ROUTE_2_DETOUR] };
  assert.equal(choiceText(choice, ROUTE_2, null), "Loading\u2026");
  assert.equal(
    choiceText(choice, ROUTE_2, detail),
    "Southbound: 17th & Washington to 17th & Mifflin",
  );
  assert.equal(
    choiceText({ ...choice, detour: "gone" }, ROUTE_2, detail),
    "Detour not found",
  );
});

// --- focusAnnouncement ------------------------------------------------------------

test("focusAnnouncement: the route and its counts, as on its row", () => {
  const counts = { active: 3, upcoming: 1, ended: 2, unknown: 0 };
  assert.equal(
    focusAnnouncement(ROUTE_2, counts),
    "Route 2 20-Johnston to Pulaski-Hunting Park: 3 now, 1 later, 2 ended.",
  );
});

test("focusAnnouncement: no detours, and back to the overview", () => {
  const none = { active: 0, upcoming: 0, ended: 0, unknown: 0 };
  assert.equal(
    focusAnnouncement({ ...ROUTE_2, short_name: "K", long_name: null }, none),
    "Route K: no detours.",
  );
  assert.equal(focusAnnouncement(null), "All routes.");
});
