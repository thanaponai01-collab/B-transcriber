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
    if (typeof el.getAttribute === "function") {
      if (el.getAttribute("placeholder") !== placeholder) {
        if (typeof el.setAttribute === "function") el.setAttribute("placeholder", placeholder);
      }
    } else if (typeof el.setAttribute === "function") {
      el.setAttribute("placeholder", placeholder);
    }
    if (document.activeElement !== el && el.value !== value) el.value = value;
    const wrap = el.parentElement;
    if (wrap && typeof wrap.querySelector === "function") {
      const valEl = wrap.querySelector(".val-text");
      if (valEl) {
        valEl.textContent = value || placeholder || "—";
        if (valEl.classList && typeof valEl.classList.toggle === "function") {
          valEl.classList.toggle("placeholder", !value && !!placeholder);
          valEl.classList.toggle("disabled", disabled);
        }
      }
      if (wrap.classList && typeof wrap.classList.toggle === "function") {
        wrap.classList.toggle("disabled", disabled);
      }
    }
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
      if (node.classList && typeof node.classList.contains === "function") {
        if (node.classList.contains("disabled") !== off) node.classList.toggle("disabled", off);
      } else if (node.classList) {
        node.classList.toggle("disabled", off);
      }
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

    const scaleReset = $("align-scale-reset");
    if (scaleReset) scaleReset.addEventListener("click", () => intents.onSetField("scale", "100"));
    const rotReset = $("align-rotation-reset");
    if (rotReset) rotReset.addEventListener("click", () => intents.onSetField("rotation", "0"));

    for (const [id] of INPUTS) {
      const input = $(id);
      if (!input) continue;
      const field = input.getAttribute("data-field");
      input.addEventListener("change", (e) => intents.onSetField(field, e.target.value));

      const wrap = input.parentElement;
      const targetEl = wrap || input;
      const valText = wrap && typeof wrap.querySelector === "function" ? wrap.querySelector(".val-text") : null;
      const valUnit = wrap && typeof wrap.querySelector === "function" ? wrap.querySelector(".val-unit") : null;

      function enterEditMode() {
        if (input.disabled) return;
        if (wrap && wrap.classList && typeof wrap.classList.add === "function") {
          wrap.classList.add("active-editing");
        }
        setHidden(valText, true);
        setHidden(valUnit, true);
        setHidden(input, false);
        if (typeof input.focus === "function") input.focus();
        if (typeof input.select === "function") input.select();
      }

      function exitEditMode(commit) {
        if (wrap && wrap.classList && typeof wrap.classList.contains === "function") {
          if (!wrap.classList.contains("active-editing")) return;
          wrap.classList.remove("active-editing");
        }
        setHidden(input, true);
        setHidden(valText, false);
        setHidden(valUnit, false);
        if (valText) {
          valText.textContent = input.value || (input.getAttribute && input.getAttribute("placeholder")) || "—";
        }
        if (commit) {
          intents.onSetField(field, input.value);
        }
      }

      // Scrubby slider: slide left/right on box to adjust value smoothly, or click to edit
      if (typeof targetEl.addEventListener === "function") {
        targetEl.addEventListener("pointerdown", (e) => {
          if (input.disabled) return;
          if (e.button !== undefined && e.button !== 0) return;
          if (wrap && wrap.classList && typeof wrap.classList.contains === "function" && wrap.classList.contains("active-editing")) {
            return;
          }

          if (typeof e.preventDefault === "function" && e.cancelable) e.preventDefault();
          const startX = e.clientX;
          const startVal = parseFloat(input.value) || 0;
          let isDragging = false;

          const onPointerMove = (me) => {
            const dx = me.clientX - startX;
            if (!isDragging && Math.abs(dx) >= 2) {
              isDragging = true;
              if (wrap && wrap.classList && typeof wrap.classList.add === "function") {
                wrap.classList.add("active-scrub");
              }
              if (typeof document !== "undefined" && document.body) {
                document.body.style.cursor = "ew-resize";
              }
            }
            if (isDragging) {
              const step = me.shiftKey ? 10 : (me.altKey || me.ctrlKey ? 0.1 : 1);
              let nextVal = startVal + dx * step;
              if (field === "scale") nextVal = Math.max(0, nextVal);
              const formatted = formatNum(nextVal);
              input.value = formatted;
              if (valText) valText.textContent = formatted;
              if (typeof intents.onSlideField === "function") {
                intents.onSlideField(field, formatted);
              }
            }
          };

          const onPointerUp = () => {
            if (typeof window !== "undefined" && typeof window.removeEventListener === "function") {
              window.removeEventListener("pointermove", onPointerMove);
              window.removeEventListener("pointerup", onPointerUp);
            }
            if (wrap && wrap.classList && typeof wrap.classList.remove === "function") {
              wrap.classList.remove("active-scrub");
            }
            if (typeof document !== "undefined" && document.body) {
              document.body.style.cursor = "";
            }
            if (isDragging) {
              if (typeof intents.onCommitField === "function") {
                intents.onCommitField(field, input.value);
              } else {
                intents.onSetField(field, input.value);
              }
            } else {
              enterEditMode();
            }
          };

          if (typeof window !== "undefined" && typeof window.addEventListener === "function") {
            window.addEventListener("pointermove", onPointerMove);
            window.addEventListener("pointerup", onPointerUp);
          }
        });
      }

      if (typeof input.addEventListener === "function") {
        input.addEventListener("blur", () => {
          exitEditMode(true);
        });
        input.addEventListener("keydown", (e) => {
          if (e.key === "Enter") {
            exitEditMode(true);
          } else if (e.key === "Escape") {
            input.value = formatNum(parseFloat(valText ? valText.textContent : input.value) || 0);
            exitEditMode(false);
          } else if (e.key === "ArrowUp" || e.key === "ArrowDown") {
            if (typeof e.preventDefault === "function") e.preventDefault();
            const step = e.shiftKey ? 10 : (e.altKey || e.ctrlKey ? 0.1 : 1);
            const delta = e.key === "ArrowUp" ? step : -step;
            let next = (parseFloat(input.value) || 0) + delta;
            if (field === "scale") next = Math.max(0, next);
            input.value = formatNum(next);
            if (valText) valText.textContent = input.value;
            if (typeof intents.onSlideField === "function") {
              intents.onSlideField(field, input.value);
            }
          }
        });
      }
    }
    const el = container();
    if (!el || typeof el.querySelectorAll !== "function") return;
    if (typeof el.addEventListener === "function") {
      const triggerPoll = () => {
        if (typeof intents.onPoll === "function") intents.onPoll();
        else if (typeof intents.onRefresh === "function") intents.onRefresh();
      };
      el.addEventListener("pointerenter", triggerPoll);
      el.addEventListener("focusin", triggerPoll);
    }
    el.querySelectorAll("[data-anchor]").forEach((node) => {
      node.addEventListener("click", () => {
        el.querySelectorAll("[data-anchor]").forEach((c) => c.classList.remove("active"));
        node.classList.add("active");
        intents.onAnchor(node.getAttribute("data-anchor"));
      });
    });
    // What the six align buttons align to: the sequence frame, or the selected clips' outer box.
    let alignTo = "frame";
    el.querySelectorAll("[data-align-to]").forEach((node) => {
      node.addEventListener("click", () => {
        alignTo = node.getAttribute("data-align-to");
        el.querySelectorAll("[data-align-to]").forEach((c) => c.classList.toggle("active", c === node));
      });
    });
    el.querySelectorAll("[data-align]").forEach((node) => {
      node.addEventListener("click", () => intents.onAlign(node.getAttribute("data-align"), alignTo));
    });
    el.querySelectorAll("[data-distribute]").forEach((node) => {
      node.addEventListener("click", () => intents.onDistribute(node.getAttribute("data-distribute"), alignTo));
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
