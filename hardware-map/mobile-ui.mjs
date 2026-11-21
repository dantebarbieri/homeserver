export const sheetMedia = "(max-width: 700px), (pointer: coarse) and (max-width: 1100px)";

// Map zoom is a percentage of the fitted size. Buttons move between 25% stops;
// pinch and trackpad gestures set any value in range.
export const zoomRange = { minimum: 75, maximum: 400, step: 25 };

export function clampZoom(value) {
  return Number.isFinite(value) ? Math.max(zoomRange.minimum, Math.min(zoomRange.maximum, value)) : 100;
}

export function stepZoom(zoom, direction) {
  const stops = zoom / zoomRange.step;
  return clampZoom((direction > 0 ? Math.floor(stops + 1e-6) + 1 : Math.ceil(stops - 1e-6) - 1) * zoomRange.step);
}

export function pinchZoom(startZoom, startDistance, distance) {
  return clampZoom(startZoom * distance / Math.max(1, startDistance));
}

// Scroll offsets that keep the content under `point` (relative to the scroll
// box) in place while the content grows from one zoom to another.
export function zoomedScroll(scroll, point, from, to) {
  const ratio = to / from;
  return { left: Math.max(0, (scroll.left + point.x) * ratio - point.x), top: Math.max(0, (scroll.top + point.y) * ratio - point.y) };
}

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
  let updateFrame = null, dragFrame = null, settling = null, opening = null;
  const viewportHeight = () => window.visualViewport?.height ?? innerHeight;
  const clamp = value => Math.max(0, Math.min(limits.full, value));
  function height(value) {
    dialog.style.setProperty("--sheet-height", `${clamp(value)}px`);
  }
  function offset(value) {
    dialog.style.setProperty("--sheet-offset", `${limits.full - clamp(value)}px`);
  }
  function stopMotion() {
    clearTimeout(settling); settling = null;
    clearTimeout(opening); opening = null;
    cancelAnimationFrame(dragFrame); dragFrame = null;
    dialog.classList.remove("sheet-opening", "sheet-dragging", "sheet-settling");
    dialog.style.removeProperty("--sheet-offset");
  }
  function visibleHeight() {
    const transform = getComputedStyle(dialog).transform;
    const translation = transform === "none" ? 0 : new DOMMatrixReadOnly(transform).m42;
    return clamp(dialog.getBoundingClientRect().height - translation);
  }
  function update() {
    dialog.classList.toggle("touch-sheet", media.matches);
    if (!media.matches || !dialog.open || drag || settling !== null || closing !== null) return;
    const chrome = [...dialog.children].filter(child => child !== body && !child.hidden)
      .reduce((sum, child) => sum + child.getBoundingClientRect().height, 0);
    const padding = parseFloat(getComputedStyle(dialog).paddingBottom) || 0;
    const nestedOverflow = [...body.querySelectorAll("[data-sheet-scroll]")].reduce(
      (sum, region) => sum + Math.max(0, region.scrollHeight - region.clientHeight), 0);
    limits = sheetHeights(viewportHeight(), chrome + body.scrollHeight + nestedOverflow + padding + 2, chrome + padding + 80);
    height(limits[snap]);
    handle.setAttribute("aria-expanded", String(snap === "full"));
    handle.setAttribute("aria-label", snap === "full" ? "Show less detail" : "Show more detail");
  }
  function scheduleUpdate() {
    if (!dialog.open || drag || settling !== null || closing !== null || updateFrame !== null) return;
    updateFrame = requestAnimationFrame(() => { updateFrame = null; update(); });
  }
  function settle(next) {
    const current = drag?.current ?? visibleHeight();
    drag = null;
    if (next === "closed") return close();
    stopMotion();
    snap = next;
    if (!media.matches || reduced.matches || Math.abs(current - limits[snap]) < 1) return update();
    // Reveal fixed-height content with a transform; only snap boundaries need layout.
    dialog.classList.add("sheet-dragging");
    height(limits.full);
    offset(current);
    dialog.getBoundingClientRect();
    dialog.classList.replace("sheet-dragging", "sheet-settling");
    offset(limits[snap]);
    handle.setAttribute("aria-expanded", String(snap === "full"));
    handle.setAttribute("aria-label", snap === "full" ? "Show less detail" : "Show more detail");
    settling = setTimeout(() => {
      height(limits[snap]);
      stopMotion();
      update();
    }, 200);
  }
  function close() {
    if (closing !== null) return;
    drag = touch = null;
    clearTimeout(settling); settling = null;
    clearTimeout(opening); opening = null;
    cancelAnimationFrame(dragFrame); dragFrame = null;
    dialog.classList.remove("sheet-opening", "sheet-settling");
    dialog.classList.remove("sheet-dragging");
    if (!media.matches || reduced.matches) return closeDialog();
    dialog.classList.add("sheet-closing");
    closing = setTimeout(() => { closing = null; closeDialog(); }, 200);
  }
  function start(y) {
    if (closing !== null) return;
    const current = visibleHeight();
    stopMotion();
    drag = { startY: y, height: current, current, previous: snap,
      moved: false, samples: [{ y, time: performance.now() }] };
    dialog.classList.add("sheet-dragging");
    height(limits.full);
    offset(current);
  }
  function move(y) {
    if (!drag) return;
    const now = performance.now();
    drag.moved ||= Math.abs(y - drag.startY) >= 10;
    drag.samples.push({ y, time: now });
    drag.samples = drag.samples.filter(sample => now - sample.time <= 100);
    drag.current = clamp(drag.height + drag.startY - y);
    if (dragFrame === null) dragFrame = requestAnimationFrame(() => {
      dragFrame = null;
      if (drag) offset(drag.current);
    });
  }
  function finish(cancelled = false) {
    if (!drag) return;
    const previous = drag.previous, moved = drag.moved, first = drag.samples[0], last = drag.samples.at(-1);
    const velocity = performance.now() - last.time <= 100 && last.time > first.time
      ? (last.y - first.y) / (last.time - first.time) : 0;
    const current = drag.current;
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
    touch = { x: point.clientX, y: point.clientY, decision: null,
      scroll: event.target.closest?.("[data-sheet-scroll]") ?? body };
  }, { passive: true });
  body.addEventListener("touchmove", event => {
    if (!touch) return;
    if (event.touches.length !== 1) { finish(true); touch = null; return; }
    const point = event.touches[0], dx = point.clientX - touch.x, dy = point.clientY - touch.y;
    if (touch.decision === null && Math.max(Math.abs(dx), Math.abs(dy)) >= 3) {
      touch.decision = dragsSheet(dx, dy, snap === "full" || limits.half === limits.full, touch.scroll.scrollTop);
      if (touch.decision) start(touch.y);
    }
    if (touch.decision) { event.preventDefault(); move(point.clientY); }
  }, { passive: false });
  body.addEventListener("touchend", () => { finish(); touch = null; });
  body.addEventListener("touchcancel", () => { finish(true); touch = null; });
  dialog.addEventListener("close", () => {
    clearTimeout(closing);
    cancelAnimationFrame(updateFrame); updateFrame = null;
    closing = drag = touch = null;
    stopMotion();
    dialog.classList.remove("sheet-closing");
  });
  new MutationObserver(scheduleUpdate).observe(body, { childList: true, subtree: true, characterData: true });
  window.addEventListener("resize", scheduleUpdate);
  window.visualViewport?.addEventListener("resize", scheduleUpdate);
  media.addEventListener("change", () => {
    if (!media.matches) {
      drag = touch = null;
      stopMotion();
    }
    update();
  });
  return {
    open() {
      clearTimeout(closing); closing = drag = touch = null;
      stopMotion();
      snap = "half";
      dialog.classList.remove("sheet-closing");
      update();
      if (media.matches && !reduced.matches) {
        dialog.classList.add("sheet-opening");
        opening = setTimeout(() => { opening = null; dialog.classList.remove("sheet-opening"); }, 200);
      }
    },
    close,
  };
}
