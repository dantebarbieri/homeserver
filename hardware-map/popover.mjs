// Anchored menus. The native Popover API supplies the top layer, light
// dismissal, Escape and "one menu at a time"; this module only places the
// panel beside its button and keeps aria-expanded current.

let activeFallback = null;

export function placePopover(anchor, size, viewport, { align = "end", gap = 6, margin = 8 } = {}) {
  const below = viewport.height - anchor.bottom - gap - margin;
  const above = anchor.top - gap - margin;
  const up = below < Math.min(size.height, 200) && above > below;
  const maxHeight = Math.max(96, up ? above : below);
  const height = Math.min(size.height, maxHeight);
  const wanted = align === "end" ? anchor.right - size.width : anchor.left;
  return {
    left: Math.max(margin, Math.min(viewport.width - size.width - margin, wanted)),
    top: up ? Math.max(margin, anchor.top - gap - height) : anchor.bottom + gap,
    maxHeight,
  };
}

export function anchorPopover(button, panel, { align = "end", onOpen, onClose } = {}) {
  const native = "popover" in panel && typeof panel.showPopover === "function";
  const isOpen = () => native ? panel.matches(":popover-open") : panel.classList.contains("menu-open");
  button.setAttribute("aria-expanded", "false");
  button.setAttribute("aria-controls", panel.id);
  panel.classList.add("menu");

  function place() {
    if (!isOpen()) return;
    panel.style.maxHeight = "";
    const viewport = { width: document.documentElement.clientWidth, height: window.visualViewport?.height ?? innerHeight };
    const bounds = panel.getBoundingClientRect();
    const spot = placePopover(button.getBoundingClientRect(), { width: bounds.width, height: bounds.height }, viewport, { align });
    panel.style.left = `${spot.left}px`;
    panel.style.top = `${spot.top}px`;
    panel.style.maxHeight = `${spot.maxHeight}px`;
    panel.classList.add("placed");
  }
  function changed(open) {
    button.setAttribute("aria-expanded", String(open));
    if (open) {
      place();
      window.addEventListener("resize", place);
      window.addEventListener("scroll", place, { passive: true, capture: true });
      onOpen?.();
    } else {
      panel.classList.remove("placed");
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place, { capture: true });
      onClose?.();
    }
  }

  if (native) {
    panel.popover = "auto";
    button.popoverTargetElement = panel;
    panel.addEventListener("toggle", event => changed(event.newState === "open"));
  } else {
    // Older browsers: same behavior without the top layer.
    const set = open => {
      if (open === isOpen()) return;
      if (open) {
        activeFallback?.(false);
        activeFallback = set;
      } else if (activeFallback === set) activeFallback = null;
      panel.classList.toggle("menu-open", open);
      changed(open);
    };
    button.addEventListener("click", () => set(!isOpen()));
    document.addEventListener("pointerdown", event => {
      if (!panel.contains(event.target) && !button.contains(event.target)) set(false);
    });
    document.addEventListener("keydown", event => {
      if (event.key === "Escape" && isOpen()) { set(false); button.focus(); }
    });
    panel.fallback = set;
  }
  return {
    get open() { return isOpen(); },
    show() { if (!isOpen()) native ? panel.showPopover() : panel.fallback(true); },
    hide() { if (isOpen()) native ? panel.hidePopover() : panel.fallback(false); },
    place,
  };
}
