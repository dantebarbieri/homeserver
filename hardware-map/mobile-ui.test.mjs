import test from "node:test";
import assert from "node:assert/strict";
import { createBottomSheet, sheetHeights, sheetSnap, dragsSheet } from "./mobile-ui.mjs";

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

function sheetFixture(t, reduced = false) {
  let now = 0, sequence = 0, reads = 0, mutation;
  const frames = new Map(), timers = new Map(), writes = [];
  class Element extends EventTarget {
    constructor() {
      super();
      const classes = new Set(), properties = new Map(), attributes = new Map();
      this.classList = {
        add: (...names) => names.forEach(name => classes.add(name)),
        remove: (...names) => names.forEach(name => classes.delete(name)),
        contains: name => classes.has(name),
        toggle: (name, on) => on ? classes.add(name) : classes.delete(name),
        replace: (before, after) => { classes.delete(before); classes.add(after); },
      };
      this.style = {
        setProperty: (name, value) => { writes.push([name, value]); properties.set(name, value); },
        getPropertyValue: name => properties.get(name) ?? "",
        removeProperty: name => properties.delete(name),
      };
      this.setAttribute = (name, value) => attributes.set(name, value);
      this.getAttribute = name => attributes.get(name);
      this.setPointerCapture = () => {};
      this.children = [];
      this.scrollTop = 0;
    }
    get scrollHeight() { reads++; return 1400; }
    getBoundingClientRect() {
      reads++;
      return { height: parseFloat(this.style.getPropertyValue("--sheet-height")) || 44 };
    }
    prepend(child) { this.children.unshift(child); }
  }
  const body = new Element(), dialog = new Element(), media = new EventTarget();
  dialog.id = "test-sheet";
  dialog.open = true;
  dialog.children.push(body);
  dialog.querySelector = () => body;
  media.matches = true;
  const globals = {
    matchMedia: query => query.includes("reduced-motion") ? { matches: reduced } : media,
    document: { createElement: () => new Element() },
    window: { addEventListener() {}, visualViewport: { height: 800, addEventListener() {} } },
    getComputedStyle: element => {
      reads++;
      return { paddingBottom: "0", transform: `matrix(1, 0, 0, 1, 0, ${parseFloat(element.style.getPropertyValue("--sheet-offset")) || 0})` };
    },
    DOMMatrixReadOnly: class { constructor(transform) { this.m42 = parseFloat(transform.split(",").at(-1)); } },
    MutationObserver: class { constructor(callback) { mutation = callback; } observe() {} },
    performance: { now: () => now },
    requestAnimationFrame: callback => { const id = ++sequence; frames.set(id, callback); return id; },
    cancelAnimationFrame: id => frames.delete(id),
    setTimeout: (callback, delay) => { const id = ++sequence; timers.set(id, { callback, at: now + delay }); return id; },
    clearTimeout: id => timers.delete(id),
  };
  for (const [name, value] of Object.entries(globals)) {
    const descriptor = Object.getOwnPropertyDescriptor(globalThis, name);
    Object.defineProperty(globalThis, name, { configurable: true, writable: true, value });
    t.after(() => descriptor ? Object.defineProperty(globalThis, name, descriptor) : delete globalThis[name]);
  }
  const sheet = createBottomSheet(dialog, () => {
    dialog.open = false;
    dialog.dispatchEvent(new Event("close"));
  });
  const dispatch = (element, type, properties = {}) => {
    const event = Object.assign(new Event(type, { cancelable: true }), properties);
    element.dispatchEvent(event);
    return event;
  };
  sheet.open();
  return {
    sheet, dialog, body, handle: dialog.children[0], media, writes, dispatch,
    get reads() { return reads; },
    get pendingFrames() { return frames.size; },
    mutate: () => mutation(),
    frame() {
      for (const [id, callback] of [...frames]) { frames.delete(id); callback(); }
    },
    advance(ms) {
      now += ms;
      for (const [id, timer] of [...timers]) if (timer.at <= now) {
        timers.delete(id); timer.callback();
      }
    },
  };
}

test("drag motion coalesces transforms without height writes or telemetry-driven layout reads", t => {
  const f = sheetFixture(t);
  f.advance(220);
  f.dispatch(f.handle, "pointerdown", { clientY: 400, button: 0, isPrimary: true, pointerId: 1 });
  const reads = f.reads, writes = f.writes.length;
  for (const y of [380, 360, 340]) {
    f.dispatch(f.handle, "pointermove", { clientY: y });
    f.mutate();
  }
  assert.equal(f.pendingFrames, 1);
  assert.equal(f.writes.length, writes);
  f.frame();
  assert.equal(f.reads, reads);
  assert.deepEqual(f.writes.slice(writes), [["--sheet-offset", "284px"]]);
  f.advance(200);
  f.dispatch(f.handle, "pointerup");
  f.advance(220);
  assert.equal(f.dialog.style.getPropertyValue("--sheet-height"), "400px");
  assert.equal(f.dialog.style.getPropertyValue("--sheet-offset"), "");
  assert.equal(f.dialog.classList.contains("sheet-opening"), false);
  f.mutate(); f.mutate();
  assert.equal(f.pendingFrames, 1);
});

test("release uses the latest unpainted drag height and cancellation restores the previous snap", t => {
  const f = sheetFixture(t);
  f.advance(220);
  f.dispatch(f.handle, "pointerdown", { clientY: 500, button: 0, isPrimary: true, pointerId: 1 });
  f.dispatch(f.handle, "pointermove", { clientY: 230 });
  f.advance(200);
  f.dispatch(f.handle, "pointerup");
  f.advance(220);
  assert.equal(f.handle.getAttribute("aria-expanded"), "true");
  assert.equal(f.dialog.style.getPropertyValue("--sheet-height"), "744px");
  f.dispatch(f.handle, "pointerdown", { clientY: 200, button: 0, isPrimary: true, pointerId: 1 });
  f.dispatch(f.handle, "pointermove", { clientY: 700 });
  f.dispatch(f.handle, "pointercancel");
  f.advance(220);
  assert.equal(f.dialog.open, true);
  assert.equal(f.dialog.style.getPropertyValue("--sheet-height"), "744px");
  assert.equal(f.pendingFrames, 0);
});

test("reduced motion settles immediately and content scroll gestures remain native", t => {
  const f = sheetFixture(t, true);
  assert.equal(f.dialog.classList.contains("sheet-opening"), false);
  f.dispatch(f.handle, "keydown", { key: "ArrowUp" });
  assert.equal(f.dialog.style.getPropertyValue("--sheet-height"), "744px");
  const gesture = (from, to) => {
    f.dispatch(f.body, "touchstart", { touches: [{ clientX: 20, clientY: from }] });
    return f.dispatch(f.body, "touchmove", { touches: [{ clientX: 20, clientY: to }] });
  };
  assert.equal(gesture(200, 100).defaultPrevented, false);
  f.dispatch(f.body, "touchend");
  f.body.scrollTop = 40;
  assert.equal(gesture(200, 300).defaultPrevented, false);
  f.dispatch(f.body, "touchend");
  f.body.scrollTop = 0;
  assert.equal(gesture(200, 240).defaultPrevented, true);
  f.dispatch(f.body, "touchmove", { touches: [{ clientX: 20, clientY: 240 }, { clientX: 40, clientY: 240 }] });
  assert.equal(f.dialog.style.getPropertyValue("--sheet-height"), "744px");
  f.sheet.close();
  assert.equal(f.dialog.open, false);
  assert.equal(f.pendingFrames, 0);
});
