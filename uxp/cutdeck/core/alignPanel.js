/* The Transform & Align panel's UI seam — the counterpart to core/panel.js, under the same
   two-export contract (render(state) / bind(intents)) and the same rule: this is the only
   place the transform panel is allowed to touch the DOM. See docs/arch-design-panel-ui.md and
   tests/panel_ui_contract.test.cjs, whose seam allowlist now names both files rather than one.

   Why this module owns a job core/panel.js does not:

   Premiere gives a plugin ONE main HTML document however many panel entrypoints it declares.
   There is no per-entrypoint "main" field — Adobe's manifest schema allows only type, id,
   label, description, shortcut, icon and the *Size hints on an entrypoint, and `main` is a
   single top-level property. Extra panels are therefore containers inside that one shared
   document, moved into their own panel root by the show() hook of entrypoints.setup(). So
   this seam exposes mount(rootNode), which relocates #view-transform out of the shared body
   and into the panel Premiere actually created for it.

   The container ships `hidden` in index.html so it never flashes inside the Cut & Sync panel
   before its own panel is opened; mount() reveals it once the move has happened.

   Nothing here may depend on hide() or destroy() firing: Adobe documents both as "not working
   as expected yet" in Premiere. unmount() exists for tests, and for a build where they work.
   A transform panel that is never unmounted is correct behavior, not a leak. */
(function (global) {
  function $(id) {
    return document.getElementById(id);
  }

  // The id of the one container this seam owns. Everything it renders lives inside it, so a
  // single lookup is enough to move the whole panel.
  const CONTAINER_ID = "view-transform";

  let current = null;

  function setText(el, value) {
    if (el && el.textContent !== value) el.textContent = value;
  }
  function setHidden(el, hidden) {
    if (el && el.hidden !== hidden) el.hidden = hidden;
  }

  // --- transform field formatting -----------------------------------------------------------
  // One decimal place matches the precision Part 1a's live probe confirmed against Effect
  // Controls' own readout (e.g. "-510.8, 44.9") — more would imply false precision, fewer would
  // stop matching it digit for digit.
  function formatNum(n) {
    return (Math.round(n * 10) / 10).toString();
  }

  // Phase 2: each value is an input. One that can't be edited safely (unread, or keyframed —
  // the panel never flattens an animation) is empty, disabled, and says why in its placeholder.
  // A field the user is typing in is never overwritten by a re-render.
  function setInput(el, value, placeholder, disabled) {
    if (!el) return;
    if (el.disabled !== disabled) el.disabled = disabled;
    if (typeof el.setAttribute === "function") el.setAttribute("placeholder", placeholder);
    if (document.activeElement !== el && el.value !== value) el.value = value;
  }
  function renderInput(id, field, key, busy) {
    const el = $(id);
    if (!field || !field.known) return setInput(el, "", "—", true);
    if (field.animated) return setInput(el, "", "keyframed", true);
    return setInput(el, formatNum(field[key]), "", !!busy);
  }

  const INPUTS = [
    ["align-position-x", "position", "x"],
    ["align-position-y", "position", "y"],
    ["align-scale", "scale", "value"],
    ["align-rotation", "rotation", "value"],
    ["align-anchor-x", "anchor", "x"],
    ["align-anchor-y", "anchor", "y"],
  ];

  // --- mount: move this panel's container into the root Premiere made for it ---------------

  function container() {
    return $(CONTAINER_ID);
  }

  /* Relocates the container into rootNode and reveals it. Idempotent: mounting into the same
     root twice is a no-op, and mounting into a different root moves it. Returns false when
     there is nothing to mount, so the caller can report a real failure instead of assuming. */
  function mount(rootNode) {
    const el = container();
    if (!el || !rootNode || typeof rootNode.appendChild !== "function") return false;
    if (el.parentElement !== rootNode) rootNode.appendChild(el);
    setHidden(el, false);
    return true;
  }

  function unmount() {
    const el = container();
    if (!el) return false;
    setHidden(el, true);
    return true;
  }

  function isMounted() {
    const el = container();
    return !!(el && el.hidden === false);
  }

  // --- render: state -> screen -------------------------------------------------------------

  // Quiet by default: the status bar shows only a problem ("error"), a skipped clip ("warn") or a
  // report the user asked for ("info", the Check Transform probe).
  function renderStatus(status) {
    if (!status) return;
    setHidden($("align-status-card"), !["error", "warn", "info"].includes(status.level));
    setText($("align-status"), status.text);
    const icon = $("align-status-icon");
    if (icon) {
      icon.classList.toggle("busy", status.level === "busy");
      icon.classList.toggle("error", status.level === "error");
      icon.classList.toggle("warn", status.level === "warn");
    }
  }

  // Every control is off while an action runs; the ones marked data-needs-clip are also off
  // while there is no editable clip.
  function renderBusy(busy, hasClip) {
    const el = container();
    if (!el || typeof el.querySelectorAll !== "function") return;
    el.querySelectorAll("[data-act]").forEach((node) => {
      const off = !!busy || (!hasClip && node.getAttribute("data-needs-clip") !== null);
      if (node.disabled !== off) node.disabled = off;
      node.classList.toggle("disabled", off);
    });
  }

  // `transform` is null when there is no sequence to read; otherwise `{ clipName, available,
  // reason, fields }`. The top line is the clip's name, or the reason nothing can be edited;
  // the fields stay in place and go blank and disabled rather than showing zeros (the plan's
  // Phase 1 Definition of Done). Returns whether there is an editable clip.
  function renderTransform(transform, busy) {
    const available = !!(transform && transform.available);
    let line = "No sequence open";
    if (transform) line = available ? (transform.clipName || "") : (transform.reason || "Unavailable.");
    setText($("align-transform-clip"), line);
    const fields = available ? (transform.fields || {}) : {};
    for (const [id, name, key] of INPUTS) renderInput(id, fields[name], key, busy);
    return available;
  }

  function render(state) {
    if (!state) return;
    current = state;
    const clipEl = $("align-transform-clip");
    if (clipEl && typeof clipEl.setAttribute === "function") {
      clipEl.setAttribute("title", state.sequence ? state.sequence.name : "No sequence open");
    }
    const hasClip = renderTransform(state.transform, state.busy);
    renderStatus(state.status);
    renderBusy(state.busy, hasClip);
  }

  // --- bind: listeners once, intents out ---------------------------------------------------

  function bind(intents) {
    const probe = $("align-probe");
    if (probe) probe.addEventListener("click", () => intents.onProbe("transform"));
    const copy = $("align-copy");
    if (copy) copy.addEventListener("click", () => intents.onProbe("copystatus"));
    const refresh = $("align-refresh");
    if (refresh) refresh.addEventListener("click", () => intents.onRefresh());

    for (const [id] of INPUTS) {
      const input = $(id);
      if (input) input.addEventListener("change", (e) => intents.onSetField(input.getAttribute("data-field"), e.target.value));
    }
    const el = container();
    if (!el || typeof el.querySelectorAll !== "function") return;
    el.querySelectorAll("[data-anchor]").forEach((node) => {
      node.addEventListener("click", () => intents.onAnchor(node.getAttribute("data-anchor")));
    });
    el.querySelectorAll("[data-align]").forEach((node) => {
      node.addEventListener("click", () => intents.onAlign(node.getAttribute("data-align")));
    });
  }

  const exportObj = { render, bind, mount, unmount, isMounted, CONTAINER_ID };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = exportObj;
  }
  if (global) {
    global.CutDeckAlignPanel = exportObj;
  }
})(typeof window !== "undefined" ? window : globalThis);
