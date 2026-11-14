export const sheetMedia = "(max-width: 700px), (pointer: coarse) and (max-width: 1100px)";

export function sheetHeights(viewport, natural, minimum = 0) {
  const full = Math.max(0, Math.min(natural, viewport - 56));
  return { half: Math.min(full, Math.max(Math.round(viewport / 2), minimum)), full };
}

export function sheetSnap(height, velocity, limits, previous = "half") {
  if (velocity < -.5) return limits.full > limits.half ? "full" : "half";
  if (velocity > .5) return previous === "full" && height >= limits.half * .6 ? "half" : "closed";
  if (height < limits.half * .6) return "closed";
  return height > (limits.half + limits.full) / 2 ? "full" : "half";
}

export function dragsSheet(dx, dy, full, scrollTop) {
  return Math.abs(dy) > Math.abs(dx) && (dy < 0 ? !full : scrollTop <= 0);
}

export function createBottomSheet(dialog, closeDialog) {
  const media = matchMedia(sheetMedia), reduced = matchMedia("(prefers-reduced-motion: reduce)");
  const body = dialog.querySelector(".popup-body");
  const handle = document.createElement("button");
  handle.type = "button";
  handle.className = "sheet-grabber";
  handle.setAttribute("aria-controls", dialog.id);
  dialog.prepend(handle);
  let snap = "half", limits = { half: 0, full: 0 }, drag = null, touch = null, closing = null, ignoreClickUntil = 0;
  const viewportHeight = () => window.visualViewport?.height ?? innerHeight;
  function height(value) {
    dialog.style.setProperty("--sheet-height", `${Math.max(0, Math.min(limits.full, value))}px`);
  }
  function update() {
    dialog.classList.toggle("touch-sheet", media.matches);
    if (!media.matches || !dialog.open) return;
    const chrome = [...dialog.children].filter(child => child !== body && !child.hidden)
      .reduce((sum, child) => sum + child.getBoundingClientRect().height, 0);
    const padding = parseFloat(getComputedStyle(dialog).paddingBottom) || 0;
    limits = sheetHeights(viewportHeight(), chrome + body.scrollHeight + padding + 2, chrome + padding + 80);
    if (!drag) height(limits[snap]);
    handle.setAttribute("aria-expanded", String(snap === "full"));
    handle.setAttribute("aria-label", snap === "full" ? "Show less detail" : "Show more detail");
  }
  function settle(next) {
    drag = null;
    dialog.classList.remove("sheet-dragging");
    if (next === "closed") return close();
    snap = next;
    update();
  }
  function close() {
    if (closing !== null) return;
    drag = touch = null;
    dialog.classList.remove("sheet-dragging");
    if (!media.matches || reduced.matches) return closeDialog();
    dialog.classList.add("sheet-closing");
    closing = setTimeout(() => { closing = null; closeDialog(); }, 200);
  }
  function start(y) {
    drag = { startY: y, height: dialog.getBoundingClientRect().height, previous: snap,
      moved: false, samples: [{ y, time: performance.now() }] };
    dialog.classList.add("sheet-dragging");
  }
  function move(y) {
    if (!drag) return;
    const now = performance.now();
    drag.moved ||= Math.abs(y - drag.startY) >= 10;
    drag.samples.push({ y, time: now });
    drag.samples = drag.samples.filter(sample => now - sample.time <= 100);
    height(drag.height + drag.startY - y);
  }
  function finish(cancelled = false) {
    if (!drag) return;
    const previous = drag.previous, moved = drag.moved, first = drag.samples[0], last = drag.samples.at(-1);
    const velocity = performance.now() - last.time <= 100 && last.time > first.time
      ? (last.y - first.y) / (last.time - first.time) : 0;
    const current = dialog.getBoundingClientRect().height;
    if (moved) ignoreClickUntil = performance.now() + 350;
    settle(cancelled || !moved ? previous : sheetSnap(current, velocity, limits, previous));
  }
  handle.addEventListener("pointerdown", event => {
    if (!media.matches || event.button !== 0 || !event.isPrimary) return;
    handle.setPointerCapture(event.pointerId);
    start(event.clientY);
    event.preventDefault();
  });
  handle.addEventListener("pointermove", event => move(event.clientY));
  handle.addEventListener("pointerup", () => finish());
  handle.addEventListener("pointercancel", () => finish(true));
  handle.addEventListener("lostpointercapture", () => finish(true));
  handle.addEventListener("click", () => {
    if (performance.now() >= ignoreClickUntil) settle(snap === "half" ? "full" : "half");
  });
  handle.addEventListener("keydown", event => {
    if (!["ArrowUp", "ArrowDown", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    settle(["ArrowUp", "End"].includes(event.key) ? "full" : "half");
  });
  body.addEventListener("touchstart", event => {
    if (!media.matches || event.touches.length !== 1) return;
    const point = event.touches[0];
    touch = { x: point.clientX, y: point.clientY, decision: null };
  }, { passive: true });
  body.addEventListener("touchmove", event => {
    if (!touch) return;
    if (event.touches.length !== 1) { finish(true); touch = null; return; }
    const point = event.touches[0], dx = point.clientX - touch.x, dy = point.clientY - touch.y;
    if (touch.decision === null && Math.max(Math.abs(dx), Math.abs(dy)) >= 3) {
      touch.decision = dragsSheet(dx, dy, snap === "full" || limits.half === limits.full, body.scrollTop);
      if (touch.decision) start(touch.y);
    }
    if (touch.decision) { event.preventDefault(); move(point.clientY); }
  }, { passive: false });
  body.addEventListener("touchend", () => { finish(); touch = null; });
  body.addEventListener("touchcancel", () => { finish(true); touch = null; });
  dialog.addEventListener("close", () => {
    clearTimeout(closing);
    closing = drag = touch = null;
    dialog.classList.remove("sheet-closing", "sheet-dragging");
  });
  new MutationObserver(update).observe(body, { childList: true, subtree: true, characterData: true });
  window.addEventListener("resize", update);
  window.visualViewport?.addEventListener("resize", update);
  media.addEventListener("change", () => { finish(true); update(); });
  return {
    open() { clearTimeout(closing); closing = null; snap = "half"; dialog.classList.remove("sheet-closing"); update(); },
    close,
  };
}
