import {turnPath} from "./globe.mjs";

export const MAX_ZOOM = 128;

export function constrainView(view, width, height) {
  const zoom = Math.max(1, Math.min(MAX_ZOOM, view.zoom));
  const baseWidth = Math.max(1000, 500 * width / height);
  const baseHeight = Math.max(500, 1000 * height / width);
  const w = baseWidth / zoom, h = baseHeight / zoom;
  return {
    zoom, width: w, height: h,
    x: w >= 1000 ? 500 : Math.max(w / 2, Math.min(1000 - w / 2, view.x)),
    y: h >= 500 ? 250 : Math.max(h / 2, Math.min(500 - h / 2, view.y)),
  };
}

export function zoomView(view, factor, position, width, height) {
  const before = constrainView(view, width, height);
  const after = constrainView({...before, zoom: before.zoom * factor}, width, height);
  return constrainView({...after,
    x: before.x + (position.x / width - .5) * (before.width - after.width),
    y: before.y + (position.y / height - .5) * (before.height - after.height),
  }, width, height);
}

export const easeInOut = t => t < .5 ? 4 * t ** 3 : 1 - (2 - 2 * t) ** 3 / 2;

// Smooth zooming and panning (van Wijk & Nuij, "Smooth and efficient zooming and panning", 2003):
// long hops pull back mid-flight so the route stays readable, then settle at the target width.
export function flyPath(from, to, rho = Math.SQRT2) {
  const dx = to.x - from.x, dy = to.y - from.y, distance = Math.hypot(dx, dy);
  const w0 = from.width, w1 = to.width, rho2 = rho * rho;
  if (distance < 1e-9) {
    return {length: Math.abs(Math.log(w1 / w0)) / rho, at: t => ({x: from.x + dx * t, y: from.y + dy * t, width: w0 * (w1 / w0) ** t})};
  }
  const b0 = (w1 * w1 - w0 * w0 + rho2 * rho2 * distance * distance) / (2 * w0 * rho2 * distance);
  const b1 = (w1 * w1 - w0 * w0 - rho2 * rho2 * distance * distance) / (2 * w1 * rho2 * distance);
  const r0 = -Math.asinh(b0), r1 = -Math.asinh(b1), length = (r1 - r0) / rho;
  return {length, at: t => {
    if (t >= 1) return {...to};
    const r = rho * t * length + r0, u = w0 / (rho2 * distance) * (Math.cosh(r0) * Math.tanh(r) - Math.sinh(r0));
    return {x: from.x + u * dx, y: from.y + u * dy, width: w0 * Math.cosh(r0) / Math.cosh(r)};
  }};
}

// Frame world-space points at no more than maxZoom, leaving margin for summary cards and controls.
export function fitView(points, maxZoom, width, height, margin = .6) {
  const xs = points.map(point => point.x), ys = points.map(point => point.y);
  const left = Math.min(...xs), right = Math.max(...xs), top = Math.min(...ys), bottom = Math.max(...ys);
  const base = constrainView({zoom: 1, x: 500, y: 250}, width, height);
  const fit = Math.min(base.width * margin / Math.max(right - left, 1e-9), base.height * margin / Math.max(bottom - top, 1e-9));
  return constrainView({zoom: Math.min(maxZoom, fit), x: (left + right) / 2, y: (top + bottom) / 2}, width, height);
}

// Keep the chosen offset from the dot even after a neighboring card expires.
export function placeArrival(x, y, width, height, bounds, placed, previous) {
  const dx = previous?.dx ?? 12, dy = previous?.dy ?? -height - 14;
  const fit = (position, limit) => Math.max(8, Math.min(position, limit - 8));
  const left = fit(x + dx, bounds.width - width), top = fit(y + dy, bounds.height - height);
  const clear = (l, t) => placed.every(p =>
    l >= p.left + p.width || l + width <= p.left || t >= p.top + p.height || t + height <= p.top);
  const preferred = {left, top, width, height, dx, dy};
  if (clear(left, top)) return preferred;

  const columns = [left, ...placed.flatMap(p => [p.left + p.width + 8, p.left - width - 8])];
  const rows = [top, ...placed.flatMap(p => [p.top + p.height + 8, p.top - height - 8])];
  let best = preferred, distance = Infinity;
  for (const column of columns) for (const row of rows) {
    const l = fit(column, bounds.width - width), t = fit(row, bounds.height - height);
    const move = Math.hypot(l - left, t - top);
    if (move < distance && clear(l, t)) {
      best = {left: l, top: t, width, height, dx: l === left ? dx : l - x, dy: t === top ? dy : t - y};
      distance = move;
    }
  }
  return best;
}

export function createMapView({panel, svg, globe, isGlobe, resetPoints, changed, closed, interacted = () => {}}) {
  const $ = id => document.getElementById(id);
  const calm = matchMedia("(prefers-reduced-motion: reduce)");
  let view = {zoom: 1, x: 500, y: 250}, frame = 0, native = false, dragging = false, suppressClickUntil = 0;
  let flight = 0, landing = null, scale = 0;
  const pointers = new Map();
  const expanded = () => panel.classList.contains("map-expanded");
  const interactive = () => expanded() || isGlobe();
  // Skipping unchanged writes keeps a rotation from invalidating layout for nothing.
  function setHidden(element, hidden) { if (element.hidden !== hidden) element.hidden = hidden; }
  function setText(element, text) { if (element.textContent !== text) element.textContent = text; }
  function setDisabled(element, disabled) { if (element.disabled !== disabled) element.disabled = disabled; }
  function draw() {
    frame = 0;
    panel.classList.toggle("globe-view", isGlobe());
    setHidden($("map-navigation"), !interactive());
    const box = svg.getBoundingClientRect();
    if (!box.width || !box.height) return;
    if (isGlobe()) {
      view.x = 500; view.y = 250;
      const base = constrainView({...view, zoom: 1}, box.width, box.height);
      globe.resize(base.width, base.height, view.zoom, box.width);
    }
    view = constrainView(view, box.width, box.height);
    // The viewBox always has the box's aspect ratio, so this is the CSS pixels per plane unit without asking the layout.
    scale = box.width / view.width;
    svg.setAttribute("viewBox", `${view.x - view.width / 2} ${view.y - view.height / 2} ${view.width} ${view.height}`);
    setText($("map-zoom-level"), `${Math.round(view.zoom * 100)}%`);
    setDisabled($("map-zoom-out"), view.zoom <= 1);
    setDisabled($("map-zoom-in"), view.zoom >= MAX_ZOOM);
    changed();
  }
  function update() { if (!frame) frame = requestAnimationFrame(draw); }
  function stopFlight() {
    if (!flight) return;
    cancelAnimationFrame(flight); flight = 0;
    const done = landing; landing = null; done?.(false);
  }
  // Globe targets {longitude, latitude} turn north-up at the current zoom; flat targets {points, zoom} fly to frame the points.
  function flyTo(target, done = () => {}) {
    stopFlight();
    const box = svg.getBoundingClientRect();
    if (!box.width || !box.height) { done(false); return; }
    view = constrainView(view, box.width, box.height);
    let duration, apply;
    if (isGlobe()) {
      const turn = turnPath(globe.rotation(), [-target.longitude, -target.latitude, 0]);
      duration = 600 + 900 * turn.angle / 180;
      apply = t => globe.rotate(turn.at(t));
    } else {
      const goal = fitView(target.points, target.zoom, box.width, box.height), base = view.width * view.zoom;
      const path = flyPath(view, goal);
      duration = Math.max(600, Math.min(1600, 400 + 500 * path.length));
      apply = t => {
        if (t >= 1) { view = goal; return; }
        const {x, y, width} = path.at(t);
        view = {x, y, zoom: base / width};
      };
    }
    const started = performance.now();
    landing = done;
    const step = now => {
      const t = calm.matches ? 1 : Math.max(0, Math.min(1, (now - started) / duration));
      apply(t >= 1 ? 1 : easeInOut(t));
      if (frame) { cancelAnimationFrame(frame); frame = 0; }
      draw();
      if (t < 1) { flight = requestAnimationFrame(step); return; }
      flight = 0; landing = null; done(true);
    };
    flight = requestAnimationFrame(step);
  }
  function reset(orientation = true) {
    stopFlight(); cancelGesture();
    view = {zoom: 1, x: 500, y: 250};
    if (orientation) globe.reset(resetPoints());
    update();
  }
  function position(x, y, box) {
    return [view.x + ((x - box.left) / box.width - .5) * view.width,
      view.y + ((y - box.top) / box.height - .5) * view.height];
  }
  function zoom(factor, clientX, clientY) {
    stopFlight();
    const box = svg.getBoundingClientRect();
    clientX ??= box.left + box.width / 2;
    clientY ??= box.top + box.height / 2;
    if (isGlobe()) {
      view = constrainView(view, box.width, box.height);
      const before = position(clientX, clientY, box);
      view = constrainView({...view, zoom: view.zoom * factor}, box.width, box.height);
      globe.drag(before, position(clientX, clientY, box));
    } else {
      view = zoomView(view, factor, {x: clientX - box.left, y: clientY - box.top}, box.width, box.height);
    }
    interacted("zoom");
    update();
  }
  // Pinches move their midpoint too; that counts as zooming, not as taking over the view.
  function pan(dx, dy, clientX, clientY, kind = "pan") {
    stopFlight();
    const box = svg.getBoundingClientRect();
    view = constrainView(view, box.width, box.height);
    if (isGlobe()) {
      clientX ??= box.left + box.width / 2;
      clientY ??= box.top + box.height / 2;
      globe.drag(position(clientX - dx, clientY - dy, box), position(clientX, clientY, box));
    } else {
      view.x -= dx * view.width / box.width;
      view.y -= dy * view.height / box.height;
    }
    interacted(kind);
    update();
  }
  function setExpanded(value) {
    panel.classList.toggle("map-expanded", value);
    document.body.classList.toggle("map-open", value);
    $("fullscreen").title = value ? "Exit full screen" : "Full screen";
    $("fullscreen").setAttribute("aria-pressed", String(value));
    $("map-navigation").hidden = !interactive();
    $("fullscreen-status").textContent = "";
    if (!value) {
      cancelGesture(); reset(false);
      $("fullscreen").focus({preventScroll: true});
      closed();
    }
    update();
  }
  async function exit() {
    if (document.fullscreenElement === panel) {
      try { await document.exitFullscreen(); }
      catch (error) { $("fullscreen-status").textContent = `Unable to exit browser fullscreen: ${error.message}`; return; }
    }
    setExpanded(false);
  }
  $("fullscreen").onclick = async () => {
    if (expanded()) { await exit(); return; }
    setExpanded(true);
    if (document.fullscreenEnabled && panel.requestFullscreen) {
      try { await panel.requestFullscreen(); }
      catch (error) { $("fullscreen-status").textContent = `Browser fullscreen unavailable; using an expanded map. ${error.message}`; }
    }
  };
  document.addEventListener("fullscreenchange", () => {
    if (document.fullscreenElement === panel) native = true;
    else if (native) { native = false; setExpanded(false); }
  });
  document.addEventListener("keydown", event => {
    if (event.key === "Escape" && expanded() && !$("detail").open) { event.preventDefault(); exit(); }
  });
  function userReset() { interacted("reset"); reset(); }
  $("map-zoom-in").onclick = () => zoom(1.5);
  $("map-zoom-out").onclick = () => zoom(1 / 1.5);
  $("map-reset").onclick = userReset;
  svg.addEventListener("wheel", event => {
    if (!interactive()) return;
    event.preventDefault();
    zoom(Math.exp(-Math.max(-200, Math.min(200, event.deltaY)) * .005), event.clientX, event.clientY);
  }, {passive: false});
  svg.addEventListener("dblclick", event => {
    if (!interactive() || event.target.closest(".map-point")) return;
    event.preventDefault(); zoom(2, event.clientX, event.clientY);
  });
  svg.addEventListener("keydown", event => {
    if (!interactive()) return;
    const moves = {ArrowLeft: [60, 0], ArrowRight: [-60, 0], ArrowUp: [0, 60], ArrowDown: [0, -60]};
    if (moves[event.key]) pan(...moves[event.key]);
    else if (["+", "="].includes(event.key)) zoom(1.5);
    else if (event.key === "-") zoom(1 / 1.5);
    else if (event.key === "0") userReset();
    else return;
    event.preventDefault();
  });
  // WebKit ignores touch-action on SVG children, so iOS took a drag starting on the globe as a page scroll and
  // cancelled it after a few pixels. Claim touches that start on anything marked touch-action:none; others still scroll.
  let claimTouch = false;
  const claims = target => {
    for (let element = target; element && element !== svg.parentElement; element = element.parentElement) {
      if (getComputedStyle(element).touchAction === "none") return true;
    }
    return false;
  };
  svg.addEventListener("touchstart", event => { claimTouch = interactive() && claims(event.target); }, {passive: true});
  svg.addEventListener("touchmove", event => { if (claimTouch && event.cancelable) event.preventDefault(); }, {passive: false});
  svg.addEventListener("pointerdown", event => {
    if (!interactive() || event.button !== 0 || pointers.size >= 2) return;
    pointers.set(event.pointerId, {x: event.clientX, y: event.clientY, startX: event.clientX, startY: event.clientY});
    if (pointers.size === 2) {
      dragging = true;
      for (const id of pointers.keys()) svg.setPointerCapture(id);
    }
  });
  window.addEventListener("pointermove", event => {
    const previous = pointers.get(event.pointerId);
    if (!interactive() || !previous) return;
    const before = [...pointers.values()];
    pointers.set(event.pointerId, {...previous, x: event.clientX, y: event.clientY});
    const after = [...pointers.values()];
    if (after.length === 2) {
      const distance = pair => Math.hypot(pair[0].x - pair[1].x, pair[0].y - pair[1].y);
      const mid = pair => ({x: (pair[0].x + pair[1].x) / 2, y: (pair[0].y + pair[1].y) / 2});
      const a = mid(before), b = mid(after);
      if (distance(before) > 0) zoom(distance(after) / distance(before), a.x, a.y);
      pan(b.x - a.x, b.y - a.y, b.x, b.y, "zoom");
    } else {
      dragging ||= Math.hypot(event.clientX - previous.startX, event.clientY - previous.startY) > 6;
      if (dragging) {
        svg.setPointerCapture(event.pointerId);
        pan(event.clientX - previous.x, event.clientY - previous.y, event.clientX, event.clientY);
      }
    }
    svg.classList.toggle("dragging", dragging);
  });
  function release(event) {
    if (!pointers.has(event.pointerId)) return;
    if (svg.hasPointerCapture(event.pointerId)) svg.releasePointerCapture(event.pointerId);
    pointers.delete(event.pointerId);
    if (dragging) suppressClickUntil = performance.now() + 400;
    if (!pointers.size) { dragging = false; svg.classList.remove("dragging"); }
  }
  window.addEventListener("pointerup", release);
  window.addEventListener("pointercancel", release);
  svg.addEventListener("lostpointercapture", release);
  function cancelGesture() {
    for (const id of [...pointers.keys()]) release({pointerId: id});
    dragging = false; svg.classList.remove("dragging");
  }
  window.addEventListener("blur", cancelGesture);
  $("projection").addEventListener("change", cancelGesture);
  svg.addEventListener("click", event => {
    if (performance.now() < suppressClickUntil) { event.preventDefault(); event.stopImmediatePropagation(); }
  }, true);
  new ResizeObserver(update).observe(svg);
  update();
  return {expanded, exit, reset, interactive, flyTo, moving: () => !!flight, held: () => pointers.size > 0,
    zoom: () => view.zoom, viewport: () => view, scale: () => scale};
}
