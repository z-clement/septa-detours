// Tests for web/js/state.js. Run: node --test web/test/

import assert from "node:assert/strict";
import { test } from "node:test";

import { createState, formatHash, parseHash } from "../js/state.js";

const NOW = new Date("2026-11-25T12:00:00Z");
const MODES = ["metro", "trolley", "bus"];

/** A store plus a log of every notification as [changed keys sorted, state]. */
function recorded() {
  const store = createState({ modes: MODES, now: NOW });
  const calls = [];
  store.subscribe((state, changed) => calls.push([[...changed].sort(), state]));
  return { store, calls };
}

test("createState starts on the overview with every mode on", () => {
  const state = createState({ modes: MODES, now: NOW }).get();
  assert.deepEqual(
    { ...state, modes: [...state.modes] },
    { focus: null, selectedDetour: null, search: "", modes: MODES, now: NOW, sheet: "half" },
  );
  assert.ok(Object.isFrozen(state));
});

test("createState copies the modes it's given", () => {
  const modes = new Set(MODES);
  const store = createState({ modes, now: NOW });
  modes.delete("bus");
  assert.ok(store.get().modes.has("bus"));
});

test("focus sets the route and the detour, and notifies both keys", () => {
  const { store, calls } = recorded();
  store.focus("bus-21", "5d0d22dfe7d86935");
  assert.equal(calls.length, 1);
  assert.deepEqual(calls[0][0], ["focus", "selectedDetour"]);
  assert.equal(calls[0][1], store.get());
  assert.equal(store.get().focus, "bus-21");
  assert.equal(store.get().selectedDetour, "5d0d22dfe7d86935");
});

test("focus without a detour clears the selected one", () => {
  const { store, calls } = recorded();
  store.focus("bus-21", "abc");
  store.focus("bus-2");
  assert.deepEqual(calls[1][0], ["focus", "selectedDetour"]);
  assert.equal(store.get().selectedDetour, null);
});

test("focus on the same route only changes the detour", () => {
  const { store, calls } = recorded();
  store.focus("bus-21", "abc");
  store.focus("bus-21", "def");
  assert.deepEqual(calls[1][0], ["selectedDetour"]);
});

test("focus(null) returns to the overview, dropping any detour given", () => {
  const { store } = recorded();
  store.focus("bus-21", "abc");
  store.focus(null, "def");
  assert.equal(store.get().focus, null);
  assert.equal(store.get().selectedDetour, null);
});

test("an action that changes nothing notifies no one", () => {
  const { store, calls } = recorded();
  store.focus(null);
  store.setSearch("");
  store.setNow(new Date(NOW.getTime())); // same instant, new object
  assert.equal(calls.length, 0);
});

test("setSearch and setNow notify their own key", () => {
  const { store, calls } = recorded();
  store.setSearch("21");
  const later = new Date("2026-11-25T12:01:00Z");
  store.setNow(later);
  assert.deepEqual(
    calls.map(([changed]) => changed),
    [["search"], ["now"]],
  );
  assert.equal(store.get().search, "21");
  assert.equal(store.get().now, later);
});

test("toggleMode switches a mode off and on with a new Set each time", () => {
  const { store, calls } = recorded();
  const before = store.get();
  store.toggleMode("trolley");
  assert.deepEqual([...store.get().modes], ["metro", "bus"]);
  assert.deepEqual([...before.modes], MODES, "the old snapshot is untouched");
  store.toggleMode("trolley");
  assert.deepEqual([...store.get().modes].sort(), [...MODES].sort());
  assert.deepEqual(
    calls.map(([changed]) => changed),
    [["modes"], ["modes"]],
  );
});

test("cycleSheet steps half -> full -> peek -> half, notifying sheet", () => {
  const { store, calls } = recorded();
  const seen = [];
  for (let i = 0; i < 3; i += 1) {
    store.cycleSheet();
    seen.push(store.get().sheet);
  }
  assert.deepEqual(seen, ["full", "peek", "half"]);
  assert.deepEqual(
    calls.map(([changed]) => changed),
    [["sheet"], ["sheet"], ["sheet"]],
  );
});

test("raiseSheet raises, and a raise that doesn't change it notifies no one", () => {
  const { store, calls } = recorded();
  store.raiseSheet("half"); // already half
  store.raiseSheet("peek"); // never lowers
  assert.equal(calls.length, 0);
  store.raiseSheet("full");
  assert.equal(store.get().sheet, "full");
  assert.deepEqual(calls[0][0], ["sheet"]);
});

test("every snapshot is frozen and earlier ones don't change", () => {
  const { store } = recorded();
  const first = store.get();
  store.setSearch("market");
  assert.ok(Object.isFrozen(store.get()));
  assert.equal(first.search, "");
  assert.notEqual(store.get(), first);
});

test("unsubscribe stops notifications; other listeners still get them", () => {
  const store = createState({ modes: MODES, now: NOW });
  const a = [];
  const b = [];
  const stopA = store.subscribe(() => a.push(1));
  store.subscribe(() => b.push(1));
  store.setSearch("x");
  stopA();
  store.setSearch("y");
  assert.deepEqual([a.length, b.length], [1, 2]);
});

test("parseHash reads the route and the detour", () => {
  assert.deepEqual(parseHash("#route=bus-21&detour=5d0d22dfe7d86935"), {
    focus: "bus-21",
    selectedDetour: "5d0d22dfe7d86935",
  });
  assert.deepEqual(parseHash("route=rail-AIR"), { focus: "rail-AIR", selectedDetour: null });
});

test("parseHash gives nulls for empty, missing or orphaned values", () => {
  const none = { focus: null, selectedDetour: null };
  assert.deepEqual(parseHash(""), none);
  assert.deepEqual(parseHash("#"), none);
  assert.deepEqual(parseHash("#route="), none);
  assert.deepEqual(parseHash("#detour=abc"), none, "no detour without a route");
  assert.deepEqual(parseHash("#route=&detour=abc"), none);
  assert.deepEqual(parseHash("#route=bus-2&detour="), { focus: "bus-2", selectedDetour: null });
});

test("formatHash writes the route, then the detour; '' on the overview", () => {
  assert.equal(formatHash({ focus: null, selectedDetour: null }), "");
  assert.equal(formatHash({ focus: "bus-21", selectedDetour: null }), "#route=bus-21");
  assert.equal(
    formatHash({ focus: "bus-21", selectedDetour: "5d0d22dfe7d86935" }),
    "#route=bus-21&detour=5d0d22dfe7d86935",
  );
});

test("formatHash and parseHash round-trip values that need encoding", () => {
  const value = { focus: "bus-a&b=c #1", selectedDetour: "x+y/z" };
  assert.deepEqual(parseHash(formatHash(value)), value);
});
