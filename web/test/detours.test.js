// Tests for web/js/detours.js. Run from the repo root: node --test web/test/

import assert from "node:assert/strict";
import { test } from "node:test";

import { TIMING_ORDER, detourTiming, groupByTiming } from "../js/detours.js";

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
