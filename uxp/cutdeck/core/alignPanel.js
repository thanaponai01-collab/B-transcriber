/* The Transform and Align tabs' UI seam — the counterpart to core/panel.js, under the same
   two-export contract (render(state) / bind(intents)) and the same rule: this is the only
   place the transform controls are allowed to touch the DOM. See docs/arch-design-panel-ui.md
   and tests/panel_ui_contract.test.cjs, whose seam allowlist names both files.

   Until 2026-10 this was a second panel entrypoint whose container was moved into its own
   panel root by a show() hook. It is now two tabs of the one CutDeck panel
   (docs/research/cutdeck-one-panel-plan.md): core/panel.js shows and hides #view-tools and its
   two views, and this seam renders inside that container only. */
(function (global) {
  function $(id) {
    return document.getElementById(id);
  }

  // The one container this seam owns: the Transform view, the Align view and their status card.
  const CONTAINER_ID = "view-tools";

  let current = null;

  function setText(el, value) {
    if (el && el.textContent !== value) el.textContent = value;
  }
  function setHidden(el, hidden) {
    if (el && el.hidden !== hidden) el.hidden = hidden;
  }

  // --- transform field formatting -----------------------------------------------------------
  // Shown the way Effect Controls shows them, digit for digit: one fixed decimal (Part 1a's live
  // probe: "-510.8, 44.9"; a whole value reads "100.0"), Anti-flicker two ("0.00"), and Rotation
  // past a full turn as turns x degrees ("1x10.0" = 370°). transform/edit.js parses that form back.
  // A text layer's Scale and Horizontal Scale read as whole numbers in Effect Controls ("100",
  // live 2026-10-16), so they are shown that way while the rows are a text layer's.
  const DECIMALS = { "anti-flicker": 2 };
  const TEXT_DECIMALS = { scale: 0, "scale-width": 0 };
  let textLayerRows = false;
  function formatNum(n, field) {
    const digits = textLayerRows && field in TEXT_DECIMALS ? TEXT_DECIMALS[field] : (DECIMALS[field] || 1);
    const fixed = (Math.round(n * Math.pow(10, digits)) / Math.pow(10, digits)).toFixed(digits);
    return fixed === "-0.0" || fixed === "-0.00" ? fixed.slice(1) : fixed;
  }
  function formatField(field, n) {
    if (field === "rotation" && Math.abs(n) >= 360) {
      const turns = Math.trunc(n / 360);
      return `${turns}x${formatNum(n - turns * 360, field)}`;
    }
    return formatNum(n, field);
  }
  function parseShown(field, text) {
    const turns = field === "rotation" ? /^(-?\d+)\s*x\s*(-?[\d.]+)$/i.exec(String(text).trim()) : null;
    return turns ? Number(turns[1]) * 360 + Number(turns[2]) : parseFloat(text) || 0;
  }
  // The params' own ranges (Crop and Opacity percent, Anti-flicker 0..1), so a scrub stops where
  // Effect Controls stops. Anti-flicker scrubs in hundredths.
  const LIMITS = {
    scale: [0, Infinity], "scale-width": [0, Infinity], "anti-flicker": [0, 1], opacity: [0, 100],
    "crop-left": [0, 100], "crop-top": [0, 100], "crop-right": [0, 100], "crop-bottom": [0, 100],
  };
  const STEP = { "anti-flicker": 0.01 };
  function clampField(field, n) {
    const range = LIMITS[field];
    return range ? Math.min(range[1], Math.max(range[0], n)) : n;
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
        const desiredText = value || placeholder || "—";
        if (valEl.textContent !== desiredText) valEl.textContent = desiredText;
        const isPlaceholder = !value && !!placeholder;
        if (valEl.classList && typeof valEl.classList.contains === "function") {
          if (valEl.classList.contains("placeholder") !== isPlaceholder) {
            valEl.classList.toggle("placeholder", isPlaceholder);
          }
          if (valEl.classList.contains("disabled") !== disabled) {
            valEl.classList.toggle("disabled", disabled);
          }
        } else if (valEl.classList && typeof valEl.classList.toggle === "function") {
          valEl.classList.toggle("placeholder", isPlaceholder);
          valEl.classList.toggle("disabled", disabled);
        }
      }
      if (wrap.classList && typeof wrap.classList.contains === "function") {
        if (wrap.classList.contains("disabled") !== disabled) wrap.classList.toggle("disabled", disabled);
      } else if (wrap.classList && typeof wrap.classList.toggle === "function") {
        wrap.classList.toggle("disabled", disabled);
      }
    }
  }
  // A `locked` field (Scale Width while Uniform Scale is on) keeps its value but is greyed, as
  // in Effect Controls.
  function renderInput(id, field, key, busy) {
    const el = $(id);
    if (!field || !field.known) return setInput(el, "", "—", true);
    if (field.animated) return setInput(el, "", "keyframed", true);
    const name = el && typeof el.getAttribute === "function" ? el.getAttribute("data-field") : null;
    return setInput(el, formatField(name, field[key]), "", !!busy || !!field.locked);
  }

  // Effect Controls' Motion rows in its order, then Opacity. Uniform Scale is a checkbox
  // (renderUniformScale); Blend Mode is a menu (renderBlendMode).
  const INPUTS = [
    ["align-position-x", "position", "x"],
    ["align-position-y", "position", "y"],
    ["align-scale", "scale", "value"],
    ["align-scale-width", "scaleWidth", "value"],
    ["align-rotation", "rotation", "value"],
    ["align-anchor-x", "anchor", "x"],
    ["align-anchor-y", "anchor", "y"],
    ["align-anti-flicker", "antiFlicker", "value"],
    ["align-crop-left", "cropLeft", "value"],
    ["align-crop-top", "cropTop", "value"],
    ["align-crop-right", "cropRight", "value"],
    ["align-crop-bottom", "cropBottom", "value"],
    ["align-opacity", "opacity", "value"],
  ];

  // Uniform Scale on: one Scale. Off: Effect Controls relabels Motion's Scale to Scale Height
  // beside Scale Width. A text layer's Transform calls its width row Horizontal Scale.
  function renderUniformScale(field, busy) {
    const box = $("align-uniform-scale");
    const known = !!(field && field.known && !field.animated);
    const on = known ? field.value !== false : true;
    if (box) {
      if (box.checked !== on) box.checked = on;
      if (box.disabled !== (!known || !!busy)) box.disabled = !known || !!busy;
    }
    setText($("align-scale-label"), on || textLayerRows ? "Scale" : "Scale Height");
    setText($("align-scale-width-label"), textLayerRows ? "Horizontal Scale" : "Scale Width");
  }

  // Blend Mode is a menu of Premiere's own modes; an unlisted value shows blank, never a guess.
  function renderBlendMode(field, busy) {
    const el = $("align-blend-mode");
    if (!el) return;
    const known = !!(field && field.known && !field.animated);
    const disabled = !known || !!busy;
    if (el.disabled !== disabled) el.disabled = disabled;
    const wanted = known ? String(field.value) : "";
    if (document.activeElement !== el && el.value !== wanted) el.value = wanted;
  }

  function container() {
    return $(CONTAINER_ID);
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
  // B4: when needPlayheadOver is true, anchor/align/distribute buttons are disabled with tooltip.
  function renderBusy(busy, hasClip, needPlayheadOver, tooltip) {
    const el = container();
    if (!el || typeof el.querySelectorAll !== "function") return;
    el.querySelectorAll("[data-act]").forEach((node) => {
      const act = node.getAttribute("data-act");
      const isAnchorOrAlignOrDist = act === "align-anchor" || act === "align-edge" || act === "distribute";
      const off = !!busy || (!hasClip && node.getAttribute("data-needs-clip") !== null) || (!!needPlayheadOver && isAnchorOrAlignOrDist);
      if (node.disabled !== off) node.disabled = off;
      if (node.classList && typeof node.classList.contains === "function") {
        if (node.classList.contains("disabled") !== off) node.classList.toggle("disabled", off);
      } else if (node.classList) {
        node.classList.toggle("disabled", off);
      }
      if (needPlayheadOver && isAnchorOrAlignOrDist && tooltip) {
        if (typeof node.setAttribute === "function") node.setAttribute("title", tooltip);
      }
    });
  }

  // B2: Sub-layer switcher (Text 1 / Text 2 / All) when Graphic has >1 text layers
  function renderTextLayerSwitcher(textLayers, activeTarget) {
    const switcher = $("align-text-layer-switcher");
    if (!switcher) return;
    if (!textLayers || textLayers.length <= 1) {
      setHidden(switcher, true);
      switcher.innerHTML = "";
      return;
    }
    setHidden(switcher, false);
    const options = [
      ...textLayers.map((l) => ({ target: l.index, label: l.label })),
      { target: "all", label: "All" },
    ];
    // Check if switcher already has matching children to avoid recreating DOM on every poll
    const currentButtons = switcher.querySelectorAll ? switcher.querySelectorAll("[data-layer-target]") : [];
    if (currentButtons.length === options.length) {
      currentButtons.forEach((btn, idx) => {
        const opt = options[idx];
        const isActive = String(activeTarget) === String(opt.target);
        if (btn.classList && typeof btn.classList.toggle === "function") {
          btn.classList.toggle("active", isActive);
        }
      });
      return;
    }
    switcher.innerHTML = "";
    for (const opt of options) {
      const btn = document.createElement("div");
      btn.className = `pill-mini${String(activeTarget) === String(opt.target) ? " active" : ""}`;
      btn.setAttribute("role", "button");
      btn.setAttribute("data-layer-target", String(opt.target));
      btn.textContent = opt.label;
      switcher.appendChild(btn);
    }
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
    textLayerRows = available && transform.layer === "text";
    for (const [id, name, key] of INPUTS) renderInput(id, fields[name], key, busy);
    renderUniformScale(available ? fields.uniformScale : null, busy);
    renderTextLayerSwitcher(transform && transform.textLayers, transform ? transform.activeLayerTarget : 0);
    return available;
  }

  // The Align tab's frame drawing takes the sequence's shape, capped in height so a 9:16 frame
  // gets narrower instead of taller. Laid out in px (percent is not a documented UXP unit) and
  // only when the size changes; clientWidth is 0 while the tab is hidden, so it waits until shown.
  const FRAME_MAX_HEIGHT = 200;
  const LINE_HIT = 12;
  let frameKey = "";
  function px(el, left, top, width, height) {
    if (!el || !el.style) return;
    el.style.left = `${Math.round(left)}px`;
    el.style.top = `${Math.round(top)}px`;
    el.style.width = `${Math.round(width)}px`;
    el.style.height = `${Math.round(height)}px`;
  }
  function frameBox(available, frame) {
    const ratio = frame && frame.width > 0 && frame.height > 0 ? frame.height / frame.width : 9 / 16;
    let width = available;
    let height = width * ratio;
    if (height > FRAME_MAX_HEIGHT) {
      height = FRAME_MAX_HEIGHT;
      width = height / ratio;
    }
    return { width: Math.round(width), height: Math.round(height) };
  }
  function renderFrame(frame) {
    const wrap = $("align-frame-wrap");
    const canvas = $("align-frame");
    if (!wrap || !canvas) return;
    const available = wrap.clientWidth || 0;
    if (available <= 0) return;
    const { width, height } = frameBox(available, frame);
    const key = `${width}x${height}`;
    if (key === frameKey) return;
    frameKey = key;
    if (canvas.style) {
      canvas.style.width = `${width}px`;
      canvas.style.height = `${height}px`;
    }
    layoutFrame(width - 2 * FRAME_BORDER, height - 2 * FRAME_BORDER);
  }
  // Lines and dots are placed inside the frame's 1px border (HTMLElement.style and clientWidth:
  // reference/adobe/api/uxp.txt).
  const FRAME_BORDER = 1;
  function layoutFrame(width, height) {
    const inner = width - 2 * LINE_HIT;
    px($("align-line-left"), 0, 0, LINE_HIT, height);
    px($("align-line-right"), width - LINE_HIT, 0, LINE_HIT, height);
    px($("align-line-top"), LINE_HIT, 0, inner, LINE_HIT);
    px($("align-line-bottom"), LINE_HIT, height - LINE_HIT, inner, LINE_HIT);
    px($("align-line-hcenter"), (width - LINE_HIT) / 2, LINE_HIT, LINE_HIT, height - 2 * LINE_HIT);
    px($("align-line-vcenter"), LINE_HIT, (height - LINE_HIT) / 2, inner, LINE_HIT);
    const boxW = width * 0.38;
    const boxH = height * 0.38;
    px($("align-clip-box"), (width - boxW) / 2, (height - boxH) / 2, boxW, boxH);
    const box = $("align-clip-box");
    const dots = box && typeof box.querySelectorAll === "function" ? box.querySelectorAll("[data-anchor]") : [];
    const DOT = 15;
    dots.forEach((dot, i) => {
      px(dot, (i % 3) * boxW / 2 - DOT / 2, Math.floor(i / 3) * boxH / 2 - DOT / 2, DOT, DOT);
    });
  }

  function render(state) {
    if (!state) return;
    current = state;
    const clipEl = $("align-transform-clip");
    if (clipEl && typeof clipEl.setAttribute === "function") {
      clipEl.setAttribute("title", state.sequence ? state.sequence.name : "No sequence open");
    }
    const busyVis = state.showBusy !== undefined ? state.showBusy : state.busy;
    const hasClip = renderTransform(state.transform, busyVis);
    renderStatus(state.status);
    const needPlayhead = !!(state.transform && state.transform.needPlayheadOver);
    const tooltip = state.transform ? state.transform.tooltip : null;
    renderBusy(busyVis, hasClip, needPlayhead, tooltip);
    renderTextPositionReset(textLayerRows);
    renderFrame(state.frame);
  }

  // A text layer's Position has no fixed default (transform/edit.js RESET_FIELDS), so its reset
  // is off while the rows are a text layer's.
  function renderTextPositionReset(text) {
    const el = container();
    const node = el && typeof el.querySelector === "function" ? el.querySelector('[data-reset="position"]') : null;
    if (!node) return;
    if (!text) {
      if (typeof node.setAttribute === "function") node.setAttribute("title", "Reset Position");
      return;
    }
    if (!node.disabled) node.disabled = true;
    if (node.classList) node.classList.toggle("disabled", true);
    if (typeof node.setAttribute === "function") node.setAttribute("title", "A text layer's Position has no fixed default");
  }

  // --- bind: listeners once, intents out ---------------------------------------------------

  function bind(intents) {
    const probe = $("align-probe");
    if (probe) probe.addEventListener("click", () => intents.onProbe("transform"));
    const copy = $("align-copy");
    if (copy) copy.addEventListener("click", () => intents.onProbe("copystatus"));
    const refresh = $("align-refresh");
    if (refresh) refresh.addEventListener("click", () => intents.onRefresh());

    const uniform = $("align-uniform-scale");
    if (uniform) uniform.addEventListener("change", (e) => intents.onSetField("uniform-scale", e.target.checked ? "on" : "off"));

    for (const [id] of INPUTS) {
      const input = $(id);
      if (!input) continue;
      const field = input.getAttribute("data-field");
      // Enter/blur commit through exitEditMode, and the browser then fires change for the same
      // text: that change is swallowed once so the value is set a single time.
      let committedByExit = false;
      input.addEventListener("change", (e) => {
        if (committedByExit) { committedByExit = false; return; }
        intents.onSetField(field, e.target.value);
      });

      const wrap = input.parentElement;
      const targetEl = wrap || input;
      const valText = wrap && typeof wrap.querySelector === "function" ? wrap.querySelector(".val-text") : null;
      const valUnit = wrap && typeof wrap.querySelector === "function" ? wrap.querySelector(".val-unit") : null;

      function enterEditMode() {
        if (input.disabled) return;
        committedByExit = false;
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
          committedByExit = true;
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
          const startVal = parseShown(field, input.value);
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
              const step = (STEP[field] || 1) * (me.shiftKey ? 10 : (me.altKey || me.ctrlKey ? 0.1 : 1));
              const nextVal = clampField(field, startVal + dx * step);
              const formatted = formatField(field, nextVal);
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
            input.value = formatField(field, parseShown(field, valText ? valText.textContent : input.value));
            exitEditMode(false);
          } else if (e.key === "ArrowUp" || e.key === "ArrowDown") {
            if (typeof e.preventDefault === "function") e.preventDefault();
            const step = (STEP[field] || 1) * (e.shiftKey ? 10 : (e.altKey || e.ctrlKey ? 0.1 : 1));
            const delta = e.key === "ArrowUp" ? step : -step;
            const next = clampField(field, parseShown(field, input.value) + delta);
            input.value = formatField(field, next);
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
    // Each row's reset arrow, as in Effect Controls: one value back to its default, one Ctrl+Z.
    el.querySelectorAll("[data-reset]").forEach((node) => {
      node.addEventListener("click", () => {
        if (!node.disabled) intents.onResetField(node.getAttribute("data-reset"));
      });
    });
    // An fx block's header reset resets each of its rows in turn, skipping a row that is off.
    el.querySelectorAll("[data-reset-block]").forEach((node) => {
      node.addEventListener("click", (e) => {
        if (e && typeof e.stopPropagation === "function") e.stopPropagation();
        if (node.disabled) return;
        const block = node.getAttribute("data-reset-block");
        el.querySelectorAll("[data-reset]").forEach((row) => {
          if (row.getAttribute("data-block") === block && !row.disabled) intents.onResetField(row.getAttribute("data-reset"));
        });
      });
    });
    // Folding an fx block is presentation only, so it stays here and never reaches a controller.
    el.querySelectorAll("[data-fold]").forEach((header) => {
      header.addEventListener("click", () => {
        const block = $(header.getAttribute("data-fold"));
        if (!block) return;
        const closed = block.classList.toggle("closed");
        const arrow = header.querySelector ? header.querySelector(".fx-arrow") : null;
        setText(arrow, closed ? "▸" : "▾");
      });
    });
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
    const switcher = $("align-text-layer-switcher");
    if (switcher && typeof switcher.addEventListener === "function") {
      switcher.addEventListener("click", (e) => {
        const targetBtn = e.target && typeof e.target.closest === "function" ? e.target.closest("[data-layer-target]") : (e.target && e.target.getAttribute && e.target.getAttribute("data-layer-target") ? e.target : null);
        if (!targetBtn) return;
        const rawTarget = targetBtn.getAttribute("data-layer-target");
        const parsedTarget = rawTarget === "all" ? "all" : parseInt(rawTarget, 10);
        if (typeof intents.onSelectTextLayer === "function") {
          intents.onSelectTextLayer(parsedTarget);
        }
      });
    }
  }

  const exportObj = { render, bind, CONTAINER_ID };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = exportObj;
  }
  if (global) {
    global.CutDeckAlignPanel = exportObj;
  }
})(typeof window !== "undefined" ? window : globalThis);
