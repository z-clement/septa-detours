// Tests for web/js/sheet.js. Run: node --test web/test/

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  SHEET_HEIGHTS,
  SHEET_PEEK_PX,
  SHEET_START,
  nextSheet,
  raisedSheet,
  sheetHeightPx,
} from "../js/sheet.js";

// A common phone viewport (iPhone 12-15: 390 x 844 CSS px), and a short
// landscape one where half is below the peek height.
const PHONE = 844;
const LANDSCAPE = 180;

test("SHEET_HEIGHTS: lowest first, frozen; the sheet starts at half", () => {
  assert.deepEqual(SHEET_HEIGHTS, ["peek", "half", "full"]);
  assert.ok(Object.isFrozen(SHEET_HEIGHTS));
  assert.equal(SHEET_START, "half");
});

test("nextSheet: peek -> half -> full -> peek", () => {
  assert.deepEqual(
    SHEET_HEIGHTS.map((sheet) => nextSheet(sheet)),
    ["half", "full", "peek"],
  );
});

test("raisedSheet: raises to at least the given height, never lowers", () => {
  assert.equal(raisedSheet("peek", "half"), "half");
  assert.equal(raisedSheet("peek", "full"), "full");
  assert.equal(raisedSheet("half", "half"), "half");
  assert.equal(raisedSheet("full", "half"), "full");
  assert.equal(raisedSheet("half", "peek"), "half");
});

test("sheetHeightPx: peek in pixels, half and full as fractions", () => {
  assert.deepEqual(
    SHEET_HEIGHTS.map((sheet) => sheetHeightPx(sheet, PHONE)),
    [SHEET_PEEK_PX, 422, 760], // 844 * 0.9 = 759.6, rounded
  );
  assert.equal(SHEET_PEEK_PX, 112);
});

test("sheetHeightPx: an odd viewport rounds half and full to whole pixels", () => {
  // iPhone SE: 667 CSS px tall; 333.5 and 600.3.
  assert.deepEqual(
    SHEET_HEIGHTS.map((sheet) => sheetHeightPx(sheet, 667)),
    [SHEET_PEEK_PX, 334, 600],
  );
});

test("sheetHeightPx: peek is never taller than half", () => {
  assert.deepEqual(
    SHEET_HEIGHTS.map((sheet) => sheetHeightPx(sheet, LANDSCAPE)),
    [90, 90, 162],
  );
});

test("unknown heights throw (a bug, not data)", () => {
  assert.throws(() => nextSheet("tall"), RangeError);
  assert.throws(() => raisedSheet("half", "tall"), RangeError);
  assert.throws(() => raisedSheet("tall", "half"), RangeError);
  assert.throws(() => sheetHeightPx("tall", PHONE), RangeError);
});
