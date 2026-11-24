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

export function createMapView({panel, svg, globe, isGlobe, resetPoints, changed, closed}) {
  const $ = id => document.getElementById(id);
  let view = {zoom: 1, x: 500, y: 250}, frame = 0, native = false, dragging = false, suppressClickUntil = 0;
  const pointers = new Map();
  const expanded = () => panel.classList.contains("map-expanded");
  const interactive = () => expanded() || isGlobe();
  function draw() {
    frame = 0;
    panel.classList.toggle("globe-view", isGlobe());
    $("map-navigation").hidden = !interactive();
    const box = svg.getBoundingClientRect();
    if (!box.width || !box.height) return;
    if (isGlobe()) {
      view.x = 500; view.y = 250;
      const base = constrainView({...view, zoom: 1}, box.width, box.height);
      globe.resize(base.width, base.height, view.zoom);
    }
    view = constrainView(view, box.width, box.height);
    svg.setAttribute("viewBox", `${view.x - view.width / 2} ${view.y - view.height / 2} ${view.width} ${view.height}`);
    $("map-zoom-level").textContent = `${Math.round(view.zoom * 100)}%`;
    $("map-zoom-out").disabled = view.zoom <= 1;
    $("map-zoom-in").disabled = view.zoom >= MAX_ZOOM;
    changed();
  }
  function update() { if (!frame) frame = requestAnimationFrame(draw); }
  function reset(orientation = true) {
    cancelGesture();
    view = {zoom: 1, x: 500, y: 250};
    if (orientation) globe.reset(resetPoints());
    update();
  }
  function position(x, y, box) {
    return [view.x + ((x - box.left) / box.width - .5) * view.width,
      view.y + ((y - box.top) / box.height - .5) * view.height];
  }
  function zoom(factor, clientX, clientY) {
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
    update();
  }
  function pan(dx, dy, clientX, clientY) {
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
    update();
  }
  function setExpanded(value) {
    panel.classList.toggle("map-expanded", value);
    document.body.classList.toggle("map-open", value);
    $("fullscreen").textContent = value ? "Exit full screen" : "Full screen";
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
  $("map-zoom-in").onclick = () => zoom(1.5);
  $("map-zoom-out").onclick = () => zoom(1 / 1.5);
  $("map-reset").onclick = () => reset();
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
    else if (event.key === "0") reset();
    else return;
    event.preventDefault();
  });
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
      pan(b.x - a.x, b.y - a.y, b.x, b.y);
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
  return {expanded, exit, reset, zoom: () => view.zoom, viewport: () => view};
}
