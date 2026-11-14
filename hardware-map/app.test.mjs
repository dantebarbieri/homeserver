import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const app = readFileSync(new URL("./app.mjs", import.meta.url), "utf8");
const popupFunctions = app.slice(app.indexOf("function capturePopupContext("), app.indexOf("function currentRef("));
const popupListeners = app.slice(app.indexOf("function requestPopupClose("), app.indexOf('$("inspector-back").addEventListener'));

function popupFixture(wide = true) {
  const queuedCloses = [], nodes = new Map();
  const document = new EventTarget(), dockInspector = new EventTarget();
  dockInspector.matches = wide;
  class Element extends EventTarget {
    constructor(id) {
      super();
      this.id = id;
      this.isConnected = true;
      const classes = new Set();
      this.classList = {
        contains: name => classes.has(name),
        remove: name => classes.delete(name),
        toggle: (name, on) => on ? classes.add(name) : classes.delete(name),
      };
      nodes.set(id, this);
    }
    focus() { document.activeElement = this; }
    matches(selector) { return selector === ":modal" && this.modal; }
    contains(node) { return node === this || node.dialog === this; }
    querySelector(selector) { return selector === ".popup-body" ? this.body : this.button; }
    show() { this.open = true; this.modal = false; this.button.focus(); }
    showModal() { this.show(); this.modal = true; }
    close() {
      this.open = this.modal = false;
      // Browsers dispatch close in a later task, after show()'s native focus steps.
      queuedCloses.push(() => this.dispatchEvent(new Event("close")));
    }
  }
  for (const name of ["inspector", "tools", "metrics", "services"]) {
    const dialog = new Element(`${name}-dialog`);
    dialog.button = new Element(`close-${name}`);
    dialog.button.dialog = dialog;
    dialog.body = { scrollTop: 0 };
  }
  new Element("inspector-title").dialog = nodes.get("inspector-dialog");
  for (const id of ["map-part", "other-part", "tools-button", "connector-button"]) new Element(id);
  document.documentElement = new Element("html");
  const map = { scrollLeft: 50, scrollTop: 80, scrollTo(left, top) { this.scrollLeft = left; this.scrollTop = top; } };
  const dialogs = () => [...nodes.values()].filter(node => node.open);
  document.querySelectorAll = () => dialogs();
  document.querySelector = selector => selector === ".map-scroll" ? map : dialogs().find(dialog => dialog.modal) ?? null;
  document.activeElement = nodes.get("map-part");
  const scope = vm.createContext({
    $, document, dockInspector, scrollX: 0, scrollY: 100, window: { scrollTo() {} },
    popupContexts: new Map(), popupSheets: new Map(), linkTrail: [],
    selectedPartId: "cpu", selectedId: "FAN1", sceneParts: new Map([["cpu", { label: "CPU" }]]),
    connectorMenu: { hide() {} }, statusCenter: { raise() {} }, metricUI: null,
    renderSelection() {}, renderTrail() {},
    createBottomSheet(dialog, close) {
      dialog.addEventListener("close", () => { dialog.sheetOpen = false; });
      return { open() { dialog.sheetOpen = true; }, close };
    },
  });
  function $(id) { return nodes.get(id); }
  vm.runInContext(`${popupFunctions}\n${popupListeners}`, scope);
  return {
    scope, document, map, $, dialog: $("inspector-dialog"),
    flushClose() { for (const close of queuedCloses.splice(0)) close(); },
    resize(wide) { dockInspector.matches = wide; dockInspector.dispatchEvent(new Event("change")); },
  };
}

test("the first docked selection restores native autofocus to the map and later selections keep it", () => {
  const f = popupFixture();
  f.scope.inspect(() => {});
  assert.equal(f.dialog.open, true);
  assert.equal(f.dialog.classList.contains("docked"), true);
  assert.equal(f.document.activeElement, f.$("map-part"));
  f.$("other-part").focus();
  f.scope.inspect(() => {});
  assert.equal(f.document.activeElement, f.$("other-part"));
  assert.equal(f.scope.popupContexts.get(f.dialog).opener, f.$("other-part"));
});

test("explicit inspector navigation and modal opening still focus the inspector", () => {
  const docked = popupFixture();
  docked.scope.inspect(() => {}, { focusTitle: true });
  assert.equal(docked.document.activeElement, docked.$("inspector-title"));
  const modal = popupFixture(false);
  modal.scope.inspect(() => {});
  assert.equal(modal.dialog.modal, true);
  assert.equal(modal.document.activeElement, modal.$("close-inspector"));
});

test("breakpoint reopening waits for close cleanup and preserves context, trail and Escape handling", () => {
  const f = popupFixture(false);
  f.scope.inspect(() => {});
  const context = f.scope.popupContexts.get(f.dialog);
  const trail = [{ kind: "part", id: "cpu" }, { kind: "connector", id: "FAN1" }];
  f.scope.linkTrail.push(...trail);
  for (const wide of [true, false, true]) {
    f.resize(wide);
    assert.equal(f.dialog.open, false, "wait for the queued close event before reopening");
    f.flushClose();
    assert.equal(f.dialog.open, true);
    assert.equal(f.dialog.modal, !wide);
    assert.equal(f.dialog.sheetOpen, true);
    assert.equal(f.dialog.classList.contains("docked"), wide);
    assert.equal(f.document.documentElement.classList.contains("inspector-docked"), wide);
    assert.equal(f.scope.popupContexts.get(f.dialog), context);
    assert.deepEqual(f.scope.linkTrail, trail);
  }
  f.map.scrollLeft = f.map.scrollTop = 999;
  f.document.dispatchEvent(Object.assign(new Event("keydown", { cancelable: true }), { key: "Escape" }));
  f.flushClose();
  assert.equal(f.dialog.open, false);
  assert.equal(f.dialog.sheetOpen, false);
  assert.equal(f.dialog.classList.contains("docked"), false);
  assert.equal(f.scope.popupContexts.has(f.dialog), false);
  assert.deepEqual(f.scope.linkTrail, []);
  assert.equal(f.document.activeElement, context.opener);
  assert.deepEqual([f.map.scrollLeft, f.map.scrollTop], [50, 80]);
});
