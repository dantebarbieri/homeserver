const slop = { mouse: 5, pen: 5, touch: 4 };

// Insertion slot for a dragged item: how many of the other items' centres lie before it.
export function dropIndex(centers, position) {
  return centers.filter(center => center < position).length;
}

// Pointer-driven reordering of sibling elements along one axis. `immediate` targets (grips) start after a few pixels
// with any pointer; other targets start after a mouse/pen drag or a touch press-and-hold, so native scrolling and
// the bottom-sheet gestures keep working until the hold completes.
export function createReorder({ root, axis, resolve, items, follow = () => [], scroller = null, bounds = null,
  longPress = 350, onStart = () => {}, onEnd = () => {}, onCommit }) {
  const horizontal = axis === "x";
  const coordinate = event => horizontal ? event.clientX : event.clientY;
  const offset = () => !scroller ? 0 : horizontal ? scroller.scrollLeft : scroller.scrollTop;
  let pending = null, active = null, suppressUntil = 0;

  function mark() {
    for (const element of active.marked) element.classList.remove("reorder-before", "reorder-after");
    active.marked = [];
    if (active.slot === active.index || !active.others.length) return;
    const before = active.slot < active.others.length;
    const target = before ? active.others[active.slot] : active.others.at(-1);
    for (const element of [target.element, ...follow(target.id)]) {
      element.classList.add(before ? "reorder-before" : "reorder-after");
      active.marked.push(element);
    }
  }

  function place() {
    const shift = active.pointer - active.start + offset() - active.scroll;
    const transform = `translate${horizontal ? "X" : "Y"}(${shift}px)`;
    for (const element of active.moving) element.style.transform = transform;
    const slot = dropIndex(active.centers, active.center + shift);
    if (slot !== active.slot) { active.slot = slot; mark(); }
  }

  function tick() {
    if (!active) return;
    const [low, high] = bounds ? bounds() : (box => horizontal ? [box.left, box.right] : [box.top, box.bottom])(scroller.getBoundingClientRect());
    const zone = 56, pointer = active.pointer;
    const speed = pointer < low + zone ? -Math.min(1, 1 - Math.max(0, pointer - low) / zone)
      : pointer > high - zone ? Math.min(1, 1 - Math.max(0, high - pointer) / zone) : 0;
    if (speed) {
      const before = offset(), step = Math.sign(speed) * Math.max(1, Math.round(Math.abs(speed) * 18));
      scroller[horizontal ? "scrollLeft" : "scrollTop"] += step;
      if (offset() !== before) place();
    }
    active.frame = requestAnimationFrame(tick);
  }

  function begin() {
    const candidate = pending;
    if (!candidate) return;
    clearTimeout(candidate.timer);
    pending = null;
    const list = items(), index = list.findIndex(item => item.id === candidate.id);
    if (index < 0) return;
    const scroll = offset();
    const centre = element => {
      const box = element.getBoundingClientRect();
      return (horizontal ? box.left + box.width / 2 : box.top + box.height / 2) + scroll;
    };
    const others = list.filter(item => item.id !== candidate.id);
    active = { id: candidate.id, index, slot: index, pointerId: candidate.pointerId, handle: candidate.handle,
      start: candidate.start, pointer: candidate.start, scroll, others, centers: others.map(item => centre(item.element)),
      center: centre(list[index].element), moving: [list[index].element, ...follow(candidate.id)], marked: [], frame: 0 };
    for (const element of active.moving) element.classList.add("reorder-dragging");
    document.documentElement.classList.add("reordering");
    try { candidate.handle.setPointerCapture(candidate.pointerId); } catch { /* the pointer may already be gone */ }
    if (candidate.type === "touch") navigator.vibrate?.(8);
    onStart(candidate.id);
    if (scroller) active.frame = requestAnimationFrame(tick);
    place();
  }

  function finish(commit) {
    if (pending) { clearTimeout(pending.timer); pending = null; }
    if (!active) return;
    const done = active;
    active = null;
    cancelAnimationFrame(done.frame);
    for (const element of done.moving) { element.classList.remove("reorder-dragging"); element.style.transform = ""; }
    for (const element of done.marked) element.classList.remove("reorder-before", "reorder-after");
    document.documentElement.classList.remove("reordering");
    try { done.handle.releasePointerCapture(done.pointerId); } catch { /* already released */ }
    suppressUntil = performance.now() + 350;
    const changed = commit && done.slot !== done.index;
    onEnd(changed);
    if (changed) onCommit(done.id, done.slot);
  }

  root.addEventListener("pointerdown", event => {
    if (pending || active || !event.isPrimary || (event.pointerType === "mouse" && event.button !== 0)) return;
    const target = resolve(event);
    if (!target) return;
    pending = { ...target, handle: target.handle ?? event.target, pointerId: event.pointerId, type: event.pointerType,
      x: event.clientX, y: event.clientY, start: coordinate(event), timer: 0 };
    if (event.pointerType === "touch" && !target.immediate) pending.timer = setTimeout(begin, longPress);
  });
  root.addEventListener("pointermove", event => {
    const current = active ?? pending;
    if (!current || event.pointerId !== current.pointerId) return;
    if (active) { active.pointer = coordinate(event); place(); return; }
    const moved = Math.hypot(event.clientX - pending.x, event.clientY - pending.y);
    if (pending.type === "touch" && !pending.immediate) { if (moved > 8) finish(false); }
    else if (moved >= (slop[pending.type] ?? 5)) begin();
  });
  window.addEventListener("pointerup", event => {
    if (event.pointerId === (active ?? pending)?.pointerId) finish(true);
  });
  window.addEventListener("pointercancel", event => {
    if (event.pointerId === (active ?? pending)?.pointerId) finish(false);
  });
  root.addEventListener("lostpointercapture", event => {
    if (active && event.pointerId === active.pointerId) finish(false);
  });
  root.addEventListener("touchstart", event => {
    if (resolve(event)?.immediate) event.stopPropagation();
  }, { passive: true });
  root.addEventListener("touchmove", event => {
    if (!active) return;
    event.preventDefault();
    event.stopPropagation();
  }, { passive: false });
  root.addEventListener("contextmenu", event => { if (pending || active) event.preventDefault(); });
  root.addEventListener("click", event => {
    if (performance.now() >= suppressUntil) return;
    event.preventDefault();
    event.stopPropagation();
  }, true);
  window.addEventListener("keydown", event => {
    if (!active || event.key !== "Escape") return;
    event.preventDefault();
    event.stopPropagation();
    finish(false);
  }, true);
  return { cancel: () => finish(false) };
}
