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
  function formatPoint(field) {
    if (!field || !field.known) return "—";
    if (field.animated) return "Animated (keyframed)";
    return `${formatNum(field.x)}, ${formatNum(field.y)} px`;
  }
  function formatScalar(field, unit) {
    if (!field || !field.known) return "—";
    if (field.animated) return "Animated (keyframed)";
    return `${formatNum(field.value)}${unit}`;
  }

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

  function renderStatus(status) {
    if (!status) return;
    setText($("align-status"), status.text);
    const icon = $("align-status-icon");
    if (icon) {
      icon.classList.toggle("busy", status.level === "busy");
      icon.classList.toggle("error", status.level === "error");
    }
  }

  function renderBusy(busy) {
    const el = container();
    if (!el || typeof el.querySelectorAll !== "function") return;
    el.querySelectorAll("[data-act]").forEach((node) => {
      if (node.disabled !== !!busy) node.disabled = !!busy;
      node.classList.toggle("disabled", !!busy);
    });
  }

  // Phase 1: read-only display of the selected clip's Position/Scale/Rotation/Anchor Point
  // (docs/research/cutdeck-transform-panel-plan.md). `transform` is null when there is no
  // sequence to read; otherwise `{ clipName, available, reason, fields }` — `available: false`
  // (no readable Motion component, or nothing selected) shows `reason` instead of the field
  // grid, per the plan's Definition of Done: "a clip with no readable Transform shows
  // 'unavailable' rather than zeros."
  function renderTransform(transform) {
    const clipEl = $("align-transform-clip");
    const reasonEl = $("align-transform-reason");
    const fieldsEl = $("align-transform-fields");

    if (!transform) {
      setText(clipEl, "No sequence open");
      setHidden(reasonEl, true);
      setHidden(fieldsEl, true);
      return;
    }

    setText(clipEl, transform.clipName || "No clip selected");

    if (!transform.available) {
      setText(reasonEl, transform.reason || "Unavailable.");
      setHidden(reasonEl, false);
      setHidden(fieldsEl, true);
      return;
    }

    setHidden(reasonEl, true);
    setHidden(fieldsEl, false);
    const fields = transform.fields || {};
    setText($("align-position"), formatPoint(fields.position));
    setText($("align-scale"), formatScalar(fields.scale, "%"));
    setText($("align-rotation"), formatScalar(fields.rotation, "°"));
    setText($("align-anchor"), formatPoint(fields.anchor));
  }

  function render(state) {
    if (!state) return;
    current = state;
    setText($("align-sequence"), state.sequence ? state.sequence.name : "No sequence open");
    renderTransform(state.transform);
    renderStatus(state.status);
    renderBusy(state.busy);
  }

  // --- bind: listeners once, intents out ---------------------------------------------------

  function bind(intents) {
    const probe = $("align-probe");
    if (probe) probe.addEventListener("click", () => intents.onProbe("transform"));
    const seqCard = $("align-seq-card");
    if (seqCard) seqCard.addEventListener("click", () => intents.onRefresh());
  }

  const exportObj = { render, bind, mount, unmount, isMounted, CONTAINER_ID };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = exportObj;
  }
  if (global) {
    global.CutDeckAlignPanel = exportObj;
  }
})(typeof window !== "undefined" ? window : globalThis);
