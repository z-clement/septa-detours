// Tests for web/js/detours.js. Run from the repo root: node --test web/test/

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  TIMING_ORDER,
  detourBounds,
  detourTiming,
  groupByTiming,
  hoursOf,
  inEffectKeys,
  inHours,
  isInEffect,
  localClock,
  rejoinCollection,
} from "../js/detours.js";

// Daily hours are SEPTA's local times whatever the machine's zone. This
// machine is on New York time, where a missing `timeZone` would still
// pass, so pretend to be far away (Node applies a TZ change at runtime).
process.env.TZ = "Asia/Tokyo";

// Route 2's real window (its first routes.json window), Philadelphia time;
// the same cases as Python's test_detour_timing. "now" values are in UTC,
// so a time read without its offset would be 5 hours off and show.
const START = "2026-11-11T06:30:00-05:00";
const END = "2026-11-27T16:00:00-05:00";
const AT_START = new Date("2026-11-11T11:30:00Z");
const AT_END = new Date("2026-11-27T21:00:00Z");
const TICK_MS = 1; // the smallest step a Date can take

/** `date` moved by `ms` milliseconds. */
function shift(date, ms) {
  return new Date(date.getTime() + ms);
}

// --- detourTiming -------------------------------------------------------------

test("detourTiming: inside the window is active, both ends included", () => {
  assert.equal(detourTiming(START, END, new Date("2026-11-25T12:11:23Z")), "active"); // snapshot
  assert.equal(detourTiming(START, END, AT_START), "active");
  assert.equal(detourTiming(START, END, AT_END), "active");
});

test("detourTiming: before the start is upcoming, after the end is ended", () => {
  assert.equal(detourTiming(START, END, shift(AT_START, -TICK_MS)), "upcoming");
  assert.equal(detourTiming(START, END, shift(AT_END, TICK_MS)), "ended");
});

test("detourTiming: a missing time is unknown, at any now", () => {
  // null from plain JSON, undefined from a clicked feature. A null start
  // read as 1970 would make the first `now` active instead.
  for (const [start, end] of [
    [null, END],
    [START, null],
    [null, null],
    [undefined, END],
    [START, undefined],
  ]) {
    for (const now of [shift(AT_START, -TICK_MS), AT_START, shift(AT_END, TICK_MS)]) {
      assert.equal(detourTiming(start, end, now), "unknown", `${start} to ${end} at ${now}`);
    }
  }
});

test("detourTiming: an unparseable time is unknown", () => {
  assert.equal(detourTiming("soon", END, AT_START), "unknown");
  assert.equal(detourTiming(START, "", AT_START), "unknown");
});

test("detourTiming: an end before the start is unknown", () => {
  // Swapped: either "upcoming" or "ended" could be the wrong answer.
  for (const now of [shift(AT_START, -TICK_MS), AT_START, AT_END, shift(AT_END, TICK_MS)]) {
    assert.equal(detourTiming(END, START, now), "unknown");
  }
});

test("detourTiming: a zero-length window is active only at that instant", () => {
  assert.equal(detourTiming(START, START, shift(AT_START, -TICK_MS)), "upcoming");
  assert.equal(detourTiming(START, START, AT_START), "active");
  assert.equal(detourTiming(START, START, shift(AT_START, TICK_MS)), "ended");
});

test("detourTiming: compares instants, whatever the offsets", () => {
  // The overnight window (Nov 25 3 PM to Nov 26 2 AM, Philadelphia), given
  // once in -05:00 and once in UTC: the same instants, the same answers.
  const now = new Date("2026-11-26T06:30:00Z"); // 1:30 AM Philadelphia
  assert.equal(detourTiming("2026-11-25T15:00:00-05:00", "2026-11-26T02:00:00-05:00", now), "active");
  assert.equal(detourTiming("2026-11-25T20:00:00Z", "2026-11-26T07:00:00Z", now), "active");
  assert.equal(detourTiming("2026-11-25T15:00:00-05:00", "2026-11-26T01:00:00-05:00", now), "ended");
});

test("detourTiming: a now that isn't a valid Date throws", () => {
  // The message matters: without the instanceof check, a string or number
  // would still throw a TypeError, but "now.getTime is not a function".
  // The fake has a getTime, so only the instanceof check refuses it.
  const fake = { getTime: () => AT_START.getTime() };
  for (const now of [new Date("nope"), "2026-11-25T12:00:00Z", AT_START.getTime(), undefined, fake]) {
    assert.throws(() => detourTiming(START, END, now), {
      name: "TypeError",
      message: /^now must be a valid Date, got /,
    });
  }
});

// --- groupByTiming ------------------------------------------------------------

/** A detour object with just the fields groupByTiming reads. */
function detour(sourceKey, start, end) {
  return { source_key: sourceKey, start, end };
}

const NOW = new Date("2026-11-25T12:11:23Z"); // the real snapshot's time

test("groupByTiming: active, upcoming, unknown, ended; snapshot order within", () => {
  const detours = [
    detour("ended-1", "2026-11-01T00:00:00-05:00", "2026-11-20T00:00:00-05:00"),
    detour("unknown-1", START, null),
    detour("active-1", START, END),
    detour("upcoming-1", "2026-12-01T00:00:00-05:00", "2026-12-02T00:00:00-05:00"),
    detour("active-2", "2026-11-25T00:00:00-05:00", END),
    detour("ended-2", "2026-11-02T00:00:00-05:00", "2026-11-03T00:00:00-05:00"),
  ];
  const keys = (groups) => groups.map((g) => [g.timing, g.detours.map((d) => d.source_key)]);
  assert.deepEqual(keys(groupByTiming(detours, NOW)), [
    ["active", ["active-1", "active-2"]],
    ["upcoming", ["upcoming-1"]],
    ["unknown", ["unknown-1"]],
    ["ended", ["ended-1", "ended-2"]],
  ]);
});

test("groupByTiming: groups the same objects it was given", () => {
  const only = detour("a", START, END);
  assert.equal(groupByTiming([only], NOW)[0].detours[0], only);
});

test("groupByTiming: leaves out empty groups; none for no detours", () => {
  const detours = [detour("ended-1", "2026-11-01T00:00:00-05:00", "2026-11-20T00:00:00-05:00")];
  assert.deepEqual(
    groupByTiming(detours, NOW).map((g) => g.timing),
    ["ended"],
  );
  assert.deepEqual(groupByTiming([], NOW), []);
});

test("TIMING_ORDER covers every detourTiming result, ended last", () => {
  assert.deepEqual(TIMING_ORDER, ["active", "upcoming", "unknown", "ended"]);
  assert.ok(Object.isFrozen(TIMING_ORDER));
});

// --- rejoinCollection ---------------------------------------------------------

/** A detour with a rejoin point at `[lon, lat]` (or none: null). */
function rejoining(sourceKey, start, end, lonLat) {
  const point = lonLat === null ? null : { lon: lonLat[0], lat: lonLat[1], node_id: 1 };
  return { ...detour(sourceKey, start, end), rejoin_point: point };
}

function rejoinFeature(sourceKey, lon, lat, color) {
  return {
    type: "Feature",
    geometry: { type: "Point", coordinates: [lon, lat] },
    properties: { key: "bus-2", source_key: sourceKey, color },
  };
}

test("rejoinCollection: detours in effect with a rejoin, snapshot order", () => {
  // Route 2's Passyunk & 17th, and points beside it.
  const detail = {
    key: "bus-2",
    detours: [
      rejoining("unknown-1", START, null, [-75.17462, 39.92456]),
      rejoining("ended-1", "2026-11-01T00:00:00-05:00", "2026-11-20T00:00:00-05:00", [-75.1, 39.9]),
      rejoining("active-none", START, END, null),
      rejoining("upcoming-1", "2026-12-01T00:00:00-05:00", "2026-12-02T00:00:00-05:00", [-75.2, 39.8]),
      rejoining("active-1", START, END, [-75.16963, 39.937]),
    ],
  };
  assert.deepEqual(rejoinCollection(detail, "#1A1818", NOW), {
    type: "FeatureCollection",
    features: [
      rejoinFeature("unknown-1", -75.17462, 39.92456, "#1A1818"),
      rejoinFeature("active-1", -75.16963, 39.937, "#1A1818"),
    ],
  });
});

test("rejoinCollection: none, and a null color passes through", () => {
  assert.deepEqual(rejoinCollection({ key: "bus-2", detours: [] }, null, NOW), {
    type: "FeatureCollection",
    features: [],
  });
  const detail = { key: "bus-2", detours: [rejoining("a", START, END, [-75.17, 39.93])] };
  assert.equal(rejoinCollection(detail, null, NOW).features[0].properties.color, null);
});

// --- isInEffect, inEffectKeys -------------------------------------------------

const UPCOMING = ["2026-12-01T00:00:00-05:00", "2026-12-02T00:00:00-05:00"];
const ENDED = ["2026-11-01T00:00:00-05:00", "2026-11-20T00:00:00-05:00"];

test("isInEffect: active and unknown are drawn, upcoming and ended aren't", () => {
  assert.equal(isInEffect(START, END, NOW), true);
  assert.equal(isInEffect(START, null, NOW), true);
  assert.equal(isInEffect(END, START, NOW), true); // bad dates: unknown
  assert.equal(isInEffect(...UPCOMING, NOW), false);
  assert.equal(isInEffect(...ENDED, NOW), false);
});

/** A detour feature as starts/skipped/paths.geojson carry it. */
function feature(sourceKey, start, end) {
  return {
    type: "Feature",
    geometry: { type: "Point", coordinates: [-75.1716, 39.9385] },
    properties: { key: "bus-2", source_key: sourceKey, color: "#1A1818", start, end },
  };
}

test("inEffectKeys: the source_keys of features in effect", () => {
  const features = [
    feature("active", START, END),
    feature("upcoming", ...UPCOMING),
    feature("unknown", null, END),
    feature("ended", ...ENDED),
  ];
  assert.deepEqual([...inEffectKeys(features, NOW)], ["active", "unknown"]);
});

test("inEffectKeys: follows the clock it's given", () => {
  const features = [feature("upcoming", ...UPCOMING)];
  assert.deepEqual([...inEffectKeys(features, NOW)], []);
  const later = new Date("2026-12-01T12:00:00Z");
  assert.deepEqual([...inEffectKeys(features, later)], ["upcoming"]);
});

test("inEffectKeys: none", () => {
  assert.equal(inEffectKeys([], NOW).size, 0);
});

// --- detourBounds ------------------------------------------------------------

/** A detour object with just the geometry fields detourBounds reads. */
function placed({ start = null, rejoin = null, skipped = null, path = null } = {}) {
  const point = (p) => (p === null ? null : { lon: p[0], lat: p[1], node_id: 1 });
  return { start_point: point(start), rejoin_point: point(rejoin), skipped, path };
}

test("detourBounds: every point, stretch and path counts", () => {
  // Route 2's detour round 17th, Washington, Broad, Passyunk: each edge
  // of the box comes from a different field.
  const detour = placed({
    start: [-75.1716, 39.9385], // north
    rejoin: [-75.1746, 39.9246], // west
    skipped: [
      [-75.1716, 39.9385],
      [-75.1731, 39.9240], // south
    ],
    path: [
      [-75.1716, 39.9385],
      [-75.1636, 39.9300], // east
    ],
  });
  assert.deepEqual(detourBounds([detour]), [
    [-75.1746, 39.924],
    [-75.1636, 39.9385],
  ]);
});

test("detourBounds: several detours share one box", () => {
  const a = placed({ start: [-75.2, 39.9] });
  const b = placed({ start: [-75.1, 40.05] });
  assert.deepEqual(detourBounds([a, b]), [
    [-75.2, 39.9],
    [-75.1, 40.05],
  ]);
});

test("detourBounds: a lone start point is a zero-size box", () => {
  assert.deepEqual(detourBounds([placed({ start: [-75.1716, 39.9385] })]), [
    [-75.1716, 39.9385],
    [-75.1716, 39.9385],
  ]);
});

test("detourBounds: null without geometry", () => {
  assert.equal(detourBounds([]), null);
  assert.equal(detourBounds([placed()]), null);
});

test("detourBounds: a rejoin alone, or a path alone, still counts", () => {
  assert.deepEqual(detourBounds([placed({ rejoin: [-75.17, 39.93] })]), [
    [-75.17, 39.93],
    [-75.17, 39.93],
  ]);
  const path = [
    [-75.18, 39.92],
    [-75.17, 39.93],
  ];
  assert.deepEqual(detourBounds([placed({ path })]), [
    [-75.18, 39.92],
    [-75.17, 39.93],
  ]);
});

// --- daily hours: localClock, inHours, hoursOf (U8) ---------------------------

/** A UTC instant from Philadelphia local time in November (UTC-5). */
const local = (date, time) => new Date(`2026-11-${date}T${time}:00-05:00`);
// Nov 2026: Mon 23, Tue 24, Wed 25, Thu 26, Fri 27, Sat 28, Sun 29, Mon 30.

test("localClock: SEPTA's weekday and time, not the machine's", () => {
  // NOW is 12:11:23 UTC on Wed Nov 25: 07:11 in Philadelphia (Tokyo: 21:11).
  assert.deepEqual(localClock(NOW), { day: 2, minutes: 7 * 60 + 11 });
  // Summer time (UTC-4): Sat Jul 4, 12:00 UTC is 08:00 local.
  assert.deepEqual(localClock(new Date("2026-07-04T12:00:00Z")), { day: 5, minutes: 480 });
  // Just before local midnight on Sunday.
  assert.deepEqual(localClock(local("29", "23:59")), { day: 6, minutes: 1439 });
});

// Route 2 #0: "7am - 4pm Mon thru Fri".
const WEEKDAYS_7_4 = { days: [0, 1, 2, 3, 4], start: "07:00", end: "16:00" };

test("inHours: inside the day's window, on its days", () => {
  assert.equal(inHours(WEEKDAYS_7_4, local("25", "07:00")), true); // start counts
  assert.equal(inHours(WEEKDAYS_7_4, local("25", "15:59")), true);
  assert.equal(inHours(WEEKDAYS_7_4, local("25", "06:59")), false);
  assert.equal(inHours(WEEKDAYS_7_4, local("25", "16:00")), false); // end doesn't
  assert.equal(inHours(WEEKDAYS_7_4, local("28", "10:00")), false); // Saturday
});

test("inHours: no hours is all day", () => {
  assert.equal(inHours(null, local("28", "03:00")), true);
});

test("inHours: overnight runs into the next morning", () => {
  // Route 32: "Monday thru Wednesday, 7:00PM to 5:00AM".
  const overnight = { days: [0, 1, 2], start: "19:00", end: "05:00" };
  assert.equal(inHours(overnight, local("25", "23:00")), true); // Wed evening
  assert.equal(inHours(overnight, local("26", "04:59")), true); // Thu, from Wed
  assert.equal(inHours(overnight, local("26", "05:00")), false);
  assert.equal(inHours(overnight, local("26", "19:00")), false); // Thu evening
  assert.equal(inHours(overnight, local("23", "04:00")), false); // Mon, from Sun
  assert.equal(inHours(overnight, local("23", "19:00")), true); // Mon evening
  assert.equal(inHours(overnight, local("25", "12:00")), false); // midday
});

test("hoursOf: the flat feature properties back to the detour object's shape", () => {
  const properties = { hours_days: "01234", hours_start: "07:00", hours_end: "16:00" };
  assert.deepEqual(hoursOf(properties), WEEKDAYS_7_4);
  assert.equal(hoursOf({ hours_days: null, hours_start: null, hours_end: null }), null);
  assert.equal(hoursOf({}), null); // MapLibre drops null properties
});

test("isInEffect: inside its dates but outside its hours is not drawn", () => {
  assert.equal(isInEffect(START, END, local("25", "20:00"), WEEKDAYS_7_4), false);
  assert.equal(isInEffect(START, END, local("25", "09:00"), WEEKDAYS_7_4), true);
  // Unknown dates still need the hours.
  assert.equal(isInEffect(null, END, local("25", "20:00"), WEEKDAYS_7_4), false);
  // Outside its dates, the hours don't help.
  assert.equal(isInEffect(...ENDED, local("25", "09:00"), WEEKDAYS_7_4), false);
});

test("inEffectKeys and rejoinCollection follow the hours", () => {
  const hours = { hours_days: "01234", hours_start: "07:00", hours_end: "16:00" };
  const withHours = feature("weekdays", START, END);
  Object.assign(withHours.properties, hours);
  const evening = local("25", "20:00");
  assert.deepEqual(
    [...inEffectKeys([withHours, feature("all-day", START, END)], evening)],
    ["all-day"],
  );
  const detail = {
    key: "bus-2",
    detours: [{ ...rejoining("weekdays", START, END, [-75.17, 39.93]), hours: WEEKDAYS_7_4 }],
  };
  assert.equal(rejoinCollection(detail, null, evening).features.length, 0);
  assert.equal(rejoinCollection(detail, null, local("25", "09:00")).features.length, 1);
});
