import test from "node:test";
import assert from "node:assert/strict";
import { sheetHeights, sheetSnap, dragsSheet } from "./mobile-ui.mjs";

test("sheets respect short content, viewport headroom and controls in short landscape windows", () => {
  assert.deepEqual(sheetHeights(800, 170), { half: 170, full: 170 });
  assert.deepEqual(sheetHeights(800, 1400), { half: 400, full: 744 });
  assert.deepEqual(sheetHeights(360, 1400, 280), { half: 280, full: 304 });
});

test("slow drags and directional flicks expand, collapse and dismiss consistently", () => {
  const limits = { half: 400, full: 744 };
  assert.equal(sheetSnap(200, 0, limits), "closed");
  assert.equal(sheetSnap(450, 0, limits), "half");
  assert.equal(sheetSnap(650, 0, limits), "full");
  assert.equal(sheetSnap(450, -.6, limits), "full");
  assert.equal(sheetSnap(650, .6, limits, "full"), "half");
  assert.equal(sheetSnap(350, .6, limits), "closed");
  assert.equal(sheetSnap(200, .6, limits, "full"), "closed");
  assert.equal(sheetSnap(170, -.6, { half: 170, full: 170 }), "half");
});

test("sheet gestures preserve horizontal interaction and native scrolling in expanded content", () => {
  assert.equal(dragsSheet(2, -40, false, 0), true);
  assert.equal(dragsSheet(2, -40, true, 0), false);
  assert.equal(dragsSheet(2, 40, true, 0), true);
  assert.equal(dragsSheet(2, 40, true, 20), false);
  assert.equal(dragsSheet(40, 2, false, 0), false);
});
