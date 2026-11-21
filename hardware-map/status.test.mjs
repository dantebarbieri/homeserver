import test from "node:test";
import assert from "node:assert/strict";
import { ageText, sourceGroups, healthOf, announceAfter, createStatusCenter } from "./status.mjs";
import { placePopover, anchorPopover } from "./popover.mjs";

const now = Date.parse("2026-11-14T12:00:00Z");
const live = extra => ({ mode: "live", stale: false, error: "", historyError: "", snapshotIssues: [],
  snapshot: { capturedAt: "2026-11-14T11:59:57Z", intervalSeconds: 5, sources: { cpu: { status: "ok" } } }, ...extra });

test("ages read naturally at each scale", () => {
  assert.equal(ageText(3400), "3 s");
  assert.equal(ageText(5 * 60000), "5 min");
  assert.equal(ageText(3 * 3600000), "3 h");
  assert.equal(ageText(-50), "0 s");
});

test("demo mode is labelled and never reports sources", () => {
  const health = healthOf({ mode: "demo" }, now);
  assert.equal(health.level, "demo");
  assert.deepEqual([health.items, health.sources], [[], []]);
});

test("a healthy live snapshot is quiet", () => {
  const health = healthOf(live(), now);
  assert.deepEqual([health.level, health.label, health.items.length], ["ok", "Live", 0]);
  assert.match(health.note, /Snapshot 3 s old · refreshed every 5 s/);
});

test("waiting for the first snapshot is not an error", () => {
  assert.equal(healthOf({ mode: "live", stale: true, error: "", snapshot: null }, now).level, "connecting");
});

test("collector notices become separate titled items", () => {
  const health = healthOf(live({ snapshotIssues: ["cache: kernel reports needs_check; cached metadata requires operator attention",
    "An unstructured note: with a colon"], historyError: "120s: ChasEx API returned HTTP 502" }), now);
  assert.equal(health.level, "warn");
  assert.equal(health.label, "3 issues");
  assert.deepEqual(health.items.map(item => [item.severity, item.title]),
    [["error", "cache"], ["warn", "Collector notice"], ["warn", "Chart history unavailable"]]);
  assert.equal(health.items[1].detail, "An unstructured note: with a colon");
});

test("an outage shows one cause and hides notices from the old snapshot", () => {
  const failed = healthOf(live({ stale: true, error: "ChasEx API returned HTTP 503", snapshotIssues: ["cpu: unavailable"] }), now);
  assert.deepEqual([failed.level, failed.label, failed.items.length], ["down", "No live data", 1]);
  assert.match(failed.items[0].detail, /HTTP 503.*hidden rather than shown out of date/);
  assert.deepEqual(failed.sources, []);
  const frozen = healthOf(live({ stale: true, snapshot: { capturedAt: "2026-11-14T11:58:00Z", intervalSeconds: 5 } }), now);
  assert.equal(frozen.items[0].title, "Collector has stopped updating");
  assert.match(frozen.note, /Last snapshot 2 min ago/);
});

test("per-disk SMART sources collapse without exposing identifiers", () => {
  const groups = sourceGroups({ "smart:wwn:0xAAA": { status: "ok" }, "smart:wwn:0xBBB": { status: "unavailable" },
    bmc: { status: "ok" }, "rear-fans": { status: "assumed", note: "constant" }, mystery: { status: "pending" } });
  assert.deepEqual(groups.map(group => [group.label, group.state, group.text]), [
    ["mystery", "failing", "pending"], ["SMART", "failing", "1 of 2 unavailable"],
    ["BMC sensors", "ok", "OK"], ["Rear fans", "assumed", "assumed"]]);
  assert.ok(!JSON.stringify(groups).includes("wwn"));
});

test("menus stay inside the viewport and flip above when there is no room", () => {
  const viewport = { width: 375, height: 800 };
  const below = placePopover({ left: 300, right: 360, top: 60, bottom: 100 }, { width: 280, height: 300 }, viewport);
  assert.deepEqual([below.left, below.top], [80, 106]);
  const clamped = placePopover({ left: 10, right: 60, top: 60, bottom: 100 }, { width: 280, height: 300 }, viewport);
  assert.equal(clamped.left, 8);
  const above = placePopover({ left: 300, right: 360, top: 700, bottom: 740 }, { width: 280, height: 300 }, viewport);
  assert.equal(above.top, 700 - 6 - 300);
  const start = placePopover({ left: 40, right: 100, top: 60, bottom: 100 }, { width: 200, height: 100 }, viewport, { align: "start" });
  assert.equal(start.left, 40);
});

function statusFixture(t) {
  const nodes = [];
  class Element extends EventTarget {
    constructor(tag = "div", className = "") {
      super();
      this.tag = tag;
      this.className = className;
      this.children = [];
      this.dataset = {};
      this.style = {};
      this.attributes = new Map();
      this.classList = {
        contains: name => this.className.split(" ").includes(name),
        add: name => { if (!this.classList.contains(name)) this.className += ` ${name}`; },
        remove: name => { this.className = this.className.split(" ").filter(value => value !== name).join(" "); },
        toggle: (name, on) => on ? this.classList.add(name) : this.classList.remove(name),
      };
      nodes.push(this);
    }
    set textContent(value) { this.text = value; this.children = []; }
    get textContent() { return (this.text ?? "") + this.children.map(child => child.textContent).join(""); }
    get childElementCount() { return this.children.length; }
    get firstElementChild() { return this.children[0]; }
    setAttribute(name, value) { this.attributes.set(name, value); }
    getAttribute(name) { return this.attributes.get(name); }
    append(...children) { for (const child of children) { child.parent = this; this.children.push(child); } }
    replaceChildren(...children) { this.children = []; this.append(...children); }
    remove() { if (this.parent) this.parent.children = this.parent.children.filter(child => child !== this); }
    contains(node) { return node === this || this.children.some(child => child.contains(node)); }
    querySelector(selector) {
      const matches = node => selector.startsWith(".") ? node.classList.contains(selector.slice(1)) : node.tag === selector;
      for (const child of this.children) {
        const found = matches(child) ? child : child.querySelector(selector);
        if (found) return found;
      }
      return null;
    }
    getBoundingClientRect() { return { left: 10, right: 110, top: 10, bottom: 40, width: 100, height: 100 }; }
    focus() { document.activeElement = this; }
  }
  const doc = new EventTarget(), win = new EventTarget();
  doc.documentElement = { clientWidth: 1200 };
  doc.createElement = tag => new Element(tag);
  doc.createDocumentFragment = () => new Element("fragment");
  win.visualViewport = { height: 800 };
  const originals = new Map(["document", "window"].map(name => [name, Object.getOwnPropertyDescriptor(globalThis, name)]));
  Object.assign(globalThis, { document: doc, window: win });
  t.after(() => {
    for (const node of nodes) node.fallback?.(false);
    for (const [name, descriptor] of originals) {
      if (descriptor) Object.defineProperty(globalThis, name, descriptor);
      else delete globalThis[name];
    }
  });
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const chip = new Element("button"), panel = new Element(), region = new Element();
  chip.append(new Element("span", "status-label"), new Element("span", "status-badge"));
  const center = createStatusCenter({ chip, panel, region });
  return {
    center, chip, panel, region, Element,
    update: (messages, at) => center.update(healthOf(live({ snapshotIssues: messages }), now + at), now + at),
    titles: () => region.children.map(toast => toast.querySelector("strong").textContent),
  };
}

test("flapping unrelated warnings cannot delay a persistent issue's eight-second announcement", t => {
  const f = statusFixture(t);
  const persistent = "cache: needs_check", flapping = "gpu: briefly unavailable";
  f.update([persistent], 0);
  f.update([flapping, persistent], 2000);
  f.update([persistent], 4000);
  f.update([persistent, flapping], 6000);
  f.update([persistent], announceAfter - 1);
  assert.deepEqual(f.titles(), []);
  f.update([persistent], announceAfter);
  assert.deepEqual(f.titles(), ["cache"]);
  assert.equal(f.region.firstElementChild.querySelector("p").textContent, "needs_check");
});

test("new persistent issues announce their own messages without repeating existing issues", t => {
  const f = statusFixture(t);
  const first = "cache: needs_check", second = "gpu: unavailable";
  f.update([first], 0);
  f.update([first], announceAfter);
  assert.deepEqual(f.titles(), ["cache"]);
  f.update([first, second], announceAfter + 1000);
  f.update([first, second], 2 * announceAfter + 999);
  assert.deepEqual(f.titles(), ["cache"]);
  f.update([first, second], 2 * announceAfter + 1000);
  assert.deepEqual(f.titles(), ["cache", "gpu"]);
  assert.equal(f.region.children[1].querySelector("p").textContent, "unavailable");
  f.update([second, first], 3 * announceAfter);
  assert.deepEqual(f.titles(), ["cache", "gpu"]);
  f.update([], 3 * announceAfter + 1);
  f.update([], 3 * announceAfter + 2);
  assert.deepEqual(f.titles(), ["cache", "gpu", "Live data is healthy again"]);
});

test("cleared issues restart their timer and transient issues never produce a recovery toast", t => {
  const f = statusFixture(t);
  const first = "cache: needs_check";
  f.update([first], 0);
  f.update([], 5000);
  assert.deepEqual(f.titles(), []);
  f.update([first], 6000);
  f.update([first], 6000 + announceAfter - 1);
  assert.deepEqual(f.titles(), []);
  f.update([first], 6000 + announceAfter);
  assert.deepEqual(f.titles(), ["cache"]);
  f.update([], 15000);
  assert.deepEqual(f.titles(), ["cache", "Live data is healthy again"]);
  f.update([first], 16000);
  f.update([first], 16000 + announceAfter);
  assert.deepEqual(f.titles(), ["cache", "Live data is healthy again", "cache"]);
});

test("outage age changes do not reset its timer or repeat its announcement", t => {
  const f = statusFixture(t);
  const data = live({ stale: true });
  for (const elapsed of [0, 1000, announceAfter - 1]) f.center.update(healthOf(data, now + elapsed), now + elapsed);
  assert.deepEqual(f.titles(), []);
  f.center.update(healthOf(data, now + announceAfter), now + announceAfter);
  f.center.update(healthOf(data, now + 2 * announceAfter), now + 2 * announceAfter);
  assert.deepEqual(f.titles(), ["Collector has stopped updating"]);
  assert.match(f.region.firstElementChild.querySelector("p").textContent, /11 s old/);
});

test("fallback menus stay exclusive on keyboard clicks and programmatic toast Details", t => {
  const f = statusFixture(t);
  const button = new f.Element("button"), panel = new f.Element();
  const calls = [];
  const layers = anchorPopover(button, panel, { onClose: () => calls.push("closed") });
  layers.show();
  f.chip.dispatchEvent(new Event("click"));
  assert.equal(layers.open, false);
  assert.equal(button.getAttribute("aria-expanded"), "false");
  assert.equal(f.chip.getAttribute("aria-expanded"), "true");
  button.dispatchEvent(new Event("click"));
  assert.equal(layers.open, true);
  assert.equal(f.chip.getAttribute("aria-expanded"), "false");
  f.update(["cache: needs_check"], 0);
  f.update(["cache: needs_check"], announceAfter);
  f.region.firstElementChild.querySelector(".toast-action").dispatchEvent(new Event("click"));
  assert.equal(layers.open, false);
  assert.equal(panel.classList.contains("placed"), false);
  assert.equal(f.panel.classList.contains("menu-open"), true);
  assert.equal(f.chip.getAttribute("aria-expanded"), "true");
  assert.deepEqual(calls, ["closed", "closed"]);
  document.dispatchEvent(Object.assign(new Event("keydown"), { key: "Escape" }));
  assert.equal(f.panel.classList.contains("menu-open"), false);
  assert.equal(document.activeElement, f.chip);
});
